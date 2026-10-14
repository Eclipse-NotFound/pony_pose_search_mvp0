"""Character engineering input: inspect, render a private copy, admit exact locations.

Only this module knows the native export protocol. Candidates and annotation use
the ordinary dataset workflow; a render never declares a character or pose valid.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from PIL import Image
from multispecies.catalog import fingerprint, load_json, require
from multispecies.library import _atomic_json
from multispecies.records import new_id, now
from source_catalog import media
from source_catalog.store import dumps, safe_id

SCHEMA = 'character_fla_export_v1'
MAX_FRAMES = 2048
MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_BATCH_BYTES = 512 * 1024 * 1024


def _verify_png(path):
    """Reject partial native writes before any position in this batch is published.

    Pillow's load() can display PNGs whose final chunks are truncated. verify()
    checks chunk checksums; the exact final IEND also rejects incomplete endings
    and trailing bytes. Each check opens one file without retaining image bytes.
    """
    with Path(path).open('rb') as stream:
        require(stream.read(8) == b'\x89PNG\r\n\x1a\n', '原生导出 PNG 签名无效。')
        stream.seek(0, os.SEEK_END)
        require(stream.tell() >= 20, '原生导出 PNG 文件不完整。')
        stream.seek(-12, os.SEEK_END)
        require(stream.read(12) == b'\x00\x00\x00\x00IEND\xaeB\x60\x82',
                '原生导出 PNG 缺少完整结束块或包含尾随数据。')
    try:
        with Image.open(path) as image:
            require(image.format == 'PNG', '原生导出图像不是 PNG。')
            image.verify()
    except (OSError, SyntaxError, ValueError) as exc:
        require(False, '原生导出 PNG 块或校验值损坏：'+str(exc))


class AnimateRenderer:
    """JSFL application entry, with a persistent outstanding-request guard.

    No extension installation, trust changes, shell interpolation or application
    termination. A timeout leaves the request for reconciliation, never kills An.
    """
    def __init__(self, project):
        self.state_root = Path(project)/'.probe/character-fla-runtime'

    def status(self):
        configured = os.environ.get('PONY_ANIMATE')
        candidates = [Path(configured)] if configured else [
            Path('D:/Program Files/Adobe Animate 2024/Animate.exe'),
            *[Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/f'Adobe/Adobe Animate {year}/Animate.exe'
              for year in range(2027, 2021, -1)]]
        executable = next((p for p in candidates if p.is_file()), None)
        return {'available': executable is not None, 'executable':str(executable) if executable else None,
                'reason': '在工程副本上运行 Animate 导出，不修改原文件。' if executable else
                          '未找到 Adobe Animate；可设置 PONY_ANIMATE，或生成导出包后手动运行其中的 JSFL。'}

    def run(self, bundle, checkpoint=lambda: None, timeout=600):
        info = self.status()
        self.state_root.mkdir(parents=True, exist_ok=True)
        marker = self.state_root/'pending.json'
        # Exclusive process lease is released by the OS on exit; uncertainty is
        # deliberately retained in pending.json after a timeout/interruption.
        lock = (self.state_root/'animate.lock').open('a+b')
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            raise ValueError('已有角色工程导出正在使用 Animate，请等待该任务完成。')
        try:
            result_path = Path(bundle['result_path'])
            expected_hash = (bundle.get('request') or {}).get('request_sha256')

            def terminal(path, export_id, request_hash=None):
                if not path.is_file():
                    return None
                try:
                    result = load_json(path)
                except (OSError, ValueError):
                    return None  # Native write may still be flushing.
                if (isinstance(result, dict) and result.get('export_id') == export_id and
                        result.get('state') in {'done', 'failed'} and
                        (not request_hash or result.get('request_sha256') == request_hash)):
                    return result
                return None

            already_dispatched = False
            if marker.exists():
                previous = load_json(marker)
                previous_path = Path(previous['result_path'])
                same = (previous['export_id'] == bundle['export_id'] and
                        previous_path.resolve() == result_path.resolve())
                previous_result = terminal(previous_path, previous['export_id'],
                    expected_hash if same and expected_hash else previous.get('request_sha256'))
                if previous_result is not None:
                    marker.unlink()
                    if same:
                        return previous_result
                else:
                    require(same, '另一个 Animate 任务尚未收到确定回执，不能重复投递；待核对：'+str(previous_path))
                    require(not expected_hash or not previous.get('request_sha256') or
                            previous['request_sha256'] == expected_hash, '未决请求指纹不符，不能继续等待或重复投递。')
                    already_dispatched = True
            checkpoint()
            if not already_dispatched:
                result = terminal(result_path, bundle['export_id'], expected_hash)
                if result is not None:
                    return result
                require(not result_path.exists(), '这个导出包已有未能核验的回执；不会再次执行。请核对：'+str(result_path))
                require(info['available'], info['reason'])
                _atomic_json(marker, {'export_id':bundle['export_id'], 'result_path':str(result_path),
                                      'request_sha256':expected_hash})
                try:
                    # Passing separate argv items preserves spaces and non-ASCII paths.
                    subprocess.Popen([info['executable'], bundle['script_path']],
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    marker.unlink()
                    raise
            deadline = time.monotonic()+timeout
            while time.monotonic() < deadline:
                checkpoint()
                result = terminal(result_path, bundle['export_id'], expected_hash)
                if result is not None:
                    marker.unlink()
                    return result
                time.sleep(.2)
            raise ValueError('等待 Animate 导出超时；工程副本和任务保留，未关闭应用。重试会继续等待同一请求，不会重复启动。回执：'+str(result_path))
        finally:
            lock.close()


class CharacterFlaWorkflow:
    def __init__(self, context, renderer=None):
        self.context = context
        self.sources, self.dataset = context.sources, context.dataset
        self.root = self.sources.root/'character_exports'
        self.renderer = renderer or AnimateRenderer(context.project)

    def _source(self, file_id, version_id=None):
        file = self.sources.file(file_id)
        require(file['kind'] == 'fla', '角色工程导出目前接受 FLA；XFL 可登记，目录依赖渲染待接入。')
        path, version = self.sources.verified_path(file_id, version_id)
        return file, path, version

    def inspect(self, file_id, *, refresh=False):
        from source_catalog.fla_structure import inspect_structure
        file, path, version = self._source(file_id)
        status = self.renderer.status()
        cached = self.sources.cache/('character_structure_'+version['id']+'.json')
        if not refresh and cached.is_file():
            previous = load_json(cached)
            if previous.get('timelines') and previous.get('version_id') == version['id']:
                return {**previous, 'renderer':status}
        data = inspect_structure(path)
        if data.get('container') == 'ole' and status['available']:
            pending = self.sources.cache/('character_inspection_'+version['id']+'.json')
            bundle = None
            if pending.is_file():
                previous = load_json(pending)
                directory, request = self._request(previous['export_id'])
                result_path = directory/'result.json'
                result = load_json(result_path) if result_path.is_file() else {}
                if result.get('state') != 'failed' and not (refresh and result.get('state') == 'done'):
                    bundle = {'export_id':request['export_id'],'script_path':str(directory/'export.jsfl'),
                              'result_path':str(result_path),'request':request}
            if bundle is None:
                bundle = self.prepare_export(file_id, operation='inspect')
                _atomic_json(pending, {'export_id':bundle['export_id']})
            self.renderer.run(bundle, self.sources._checkpoint)
            return self.accept_inspection(bundle['export_id'])
        require(media.identity(path) == version['sha256'], '工程在检查中发生变化，请重新扫描。')
        result = {**data, 'file_id':file_id, 'version_id':version['id'], 'renderer':status}
        # Cache only as a suggestion. prepare_export revalidates the source version.
        _atomic_json(self.sources.cache/('character_structure_'+version['id']+'.json'), result)
        return result

    def accept_inspection(self, export_id):
        _, request = self._request(export_id)
        native = self._receipt(export_id)
        require(request['operation'] == 'inspect', '这不是工程结构检查回执。')
        _,_,version = self._source(request['file_id'], request['version_id'])
        require(isinstance(native.get('timelines'),list) and all(isinstance(t,dict) and
                t.get('kind') in {'scene','symbol'} and isinstance(t.get('id'),str) and t['id'] and
                isinstance(t.get('name'),str) and t['name'] and type(t.get('frame_count')) is int and
                t['frame_count'] > 0 for t in native['timelines']), '原生时间轴信息无效。')
        require(len({t['id'] for t in native['timelines']}) == len(native['timelines']) and
                all(t['id'] == 'symbol:'+t['name'] if t['kind'] == 'symbol' else
                    type(t.get('index0')) is int and t['index0'] >= 0 and t['id'] == 'scene:'+str(t['index0'])
                    for t in native['timelines']), '原生时间轴身份重复或不一致。')
        result = {'file_id':request['file_id'],'version_id':version['id'],'container':'ole',
                  'native_inspect':True,'timelines':native['timelines'],'inspection_export_ref':export_id,
                  'warnings':['旧版工程结构来自 Animate 工作副本；复合元件仍需确认是否完整角色。',
                              '旧版脚本可能在打开时转换；此处只提供时间轴静态画面，不保证脚本驱动的播放效果。'],
                  'renderer':self.renderer.status()}
        _atomic_json(self.sources.cache/('character_structure_'+version['id']+'.json'),result)
        return result

    def _inspection(self, file_id, version):
        path = self.sources.cache/('character_structure_'+version['id']+'.json')
        data = load_json(path) if path.is_file() else self.inspect(file_id)
        require(data['version_id'] == version['id'], '工程版本已变化，请重新检查。')
        return data

    def prepare_export(self, file_id, timeline_id=None, *, start=1, stop=None, step=1,
                       actor='本机用户', set_id='set_inbox', operation='render', version_id=None):
        file, path, version = self._source(file_id, version_id)
        require(operation in {'inspect','render'}, '未知工程操作')
        safe_id(set_id)
        require(isinstance(actor,str) and 0 < len(actor.strip()) <= 100, '需要操作人名称')
        timeline, frames = None, []
        if operation == 'render':
            data = self._inspection(file_id, version)
            timeline = next((t for t in data['timelines'] if t['id'] == timeline_id), None)
            require(timeline is not None, '找不到所选工程时间轴，请重新检查。')
            stop = timeline['frame_count'] if stop is None else stop
            require(all(type(v) is int for v in (start,stop,step)) and
                    1 <= start <= stop <= timeline['frame_count'] and step > 0, '工程帧范围无效（界面从 1 开始）')
            frames = list(range(start-1,stop,step))
            require(len(frames) <= MAX_FRAMES, '一次最多导出 2048 个画面，请分段。')
            require(timeline['kind'] != 'symbol' or timeline['frame_count'] <= MAX_FRAMES,
                    '元件整段超过 2048 帧；当前原生序列导出需读取整段，请先选择较短角色时间轴。')
        export_id = new_id('character_export')
        directory = self.root/export_id
        directory.mkdir(parents=True, exist_ok=False)
        working = directory/'source.fla'
        shutil.copyfile(path, working)
        require(media.sha_file(working) == version['sha256'] == media.sha_file(path), '复制期间原工程已改变，未准备导出。')
        outputs = directory/'frames'; outputs.mkdir()
        template = Path(__file__).parents[1]/'source_catalog/character_export.jsfl'
        source = template.read_text(encoding='utf-8')
        (directory/'exporter.jsfl').write_text(source, encoding='utf-8')
        request = {'schema_version':SCHEMA, 'export_id':export_id, 'operation':operation,
                   'file_id':file_id, 'version_id':version['id'], 'source_sha256':version['sha256'],
                   'copy_uri':working.as_uri(), 'output_uri':outputs.as_uri()+'/',
                   'result_uri':(directory/'result.json').as_uri(), 'timeline':timeline, 'frames0':frames,
                   'actor':actor, 'set_id':set_id, 'exporter_sha256':hashlib.sha256(source.encode()).hexdigest(),
                   'created_at':now()}
        request['request_sha256'] = fingerprint(request)
        _atomic_json(directory/'request.json', request)
        require(source.count('__PONY_CHARACTER_REQUEST__') == 1, '原生导出模板占位符无效')
        script = source.replace('__PONY_CHARACTER_REQUEST__', json.dumps(request, ensure_ascii=True))
        (directory/'export.jsfl').write_text(script, encoding='utf-8')
        return {'export_id':export_id, 'directory':str(directory), 'script_path':str(directory/'export.jsfl'),
                'result_path':str(directory/'result.json'), 'request':request}

    def _request(self, export_id):
        directory = self.root/safe_id(export_id)
        require(directory.resolve().is_relative_to(self.root.resolve()), '导出目录无效')
        request = load_json(directory/'request.json')
        require(request.get('export_id') == export_id and request.get('schema_version') == SCHEMA and
                request.get('request_sha256') == fingerprint({k:v for k,v in request.items() if k != 'request_sha256'}),
                '导出请求指纹不符，不能建立工程位置。')
        require(media.sha_file(directory/'source.fla') == request['source_sha256'], '导出工作副本发生变化，不能建立工程位置。')
        template = (directory/'exporter.jsfl').read_text(encoding='utf-8')
        require(hashlib.sha256(template.encode()).hexdigest() == request['exporter_sha256'] and
                template.count('__PONY_CHARACTER_REQUEST__') == 1 and
                (directory/'export.jsfl').read_text(encoding='utf-8') ==
                template.replace('__PONY_CHARACTER_REQUEST__', json.dumps(request, ensure_ascii=True)),
                '实际导出脚本与请求指纹不符。')
        require(request['copy_uri'] == (directory/'source.fla').as_uri() and
                request['output_uri'] == (directory/'frames').as_uri()+'/' and
                request['result_uri'] == (directory/'result.json').as_uri(), '导出请求路径不符。')
        return directory, request

    def _receipt(self, export_id):
        directory, request = self._request(export_id)
        result = load_json(directory/'result.json')
        require(result.get('schema_version') == SCHEMA and result.get('export_id') == export_id and
                result.get('request_sha256') == request['request_sha256'] and result.get('operation') == request['operation'] and
                result.get('copy_uri') == request['copy_uri'],
                '原生导出回执与请求不匹配。')
        require(result.get('state') == 'done', 'Animate 导出失败：'+str(result.get('error') or result.get('state')))
        renderer = result.get('renderer', {})
        require(renderer.get('name') == 'Adobe Animate' and isinstance(renderer.get('version'),str) and renderer['version'],
                '缺少原生渲染器版本。')
        return result

    def accept_export(self, export_id, *, jid=None):
        directory, request = self._request(export_id)
        result = self._receipt(export_id)
        require(request['operation'] == 'render', '结构检查回执不能作为画面导入。')
        _, original, version = self._source(request['file_id'], request['version_id'])
        timeline = request['timeline']
        frames = result.get('frames')
        require(isinstance(frames,list) and 0 < len(frames) <= MAX_FRAMES and
                all(isinstance(r,dict) and type(r.get('frame_index0')) is int and isinstance(r.get('file'),str) for r in frames) and
                [r.get('frame_index0') for r in frames] == request['frames0'] and
                len({r.get('file') for r in frames}) == len(frames), '原生输出缺帧、重复或顺序不符。')
        frame_root = directory/'frames'
        require(not frame_root.is_symlink() and not getattr(frame_root,'is_junction',lambda:False)() and
                frame_root.resolve().is_relative_to(directory.resolve()), '输出图片目录超出导出目录。')
        prepared = []
        total_bytes = 0
        for frame in frames:
            self.sources._checkpoint()
            require(frame.get('timeline_id') == timeline['id'], '输出来自不同工程时间轴。')
            name = frame.get('file')
            require(isinstance(name,str) and name and Path(name).name == name and
                    '/' not in name and '\\' not in name and ':' not in name and name.lower().endswith('.png'), '输出图片路径无效。')
            image_path = directory/'frames'/name
            require(not image_path.is_symlink() and image_path.resolve().is_relative_to((directory/'frames').resolve()), '输出图片超出导出目录。')
            size_bytes = image_path.stat().st_size
            total_bytes += size_bytes
            require(0 < size_bytes <= MAX_PNG_BYTES and total_bytes <= MAX_BATCH_BYTES,
                    '导出图片超过单张 64 MB 或本批 512 MB，请缩小导出范围。')
            image_sha = media.sha_file(image_path)
            _verify_png(image_path)
            with Image.open(image_path) as im:
                require(im.format == 'PNG' and 0 < im.width*im.height <= 64_000_000, '原生导出图像格式或大小无效。')
                im.load()
                size = list(im.size)
                bounds = im.convert('RGBA').getbbox()
            prepared.append((frame,image_path,image_sha,size,bounds))
        # Validate the complete batch before publishing any positions. Source
        # versions stay frozen even if a future export produces different pixels.
        require(media.identity(original) == version['sha256'], '接收期间原工程发生变化。')
        positions, candidates = [], []
        for index,(frame,image_path,image_sha,size,bounds) in enumerate(prepared):
            self.sources._checkpoint()
            raw = image_path.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == image_sha, '导出图片在接收期间发生变化，请重试。')
            identity = [request['file_id'],request['version_id'],timeline['id'],frame['frame_index0'],
                        result['renderer'],request['exporter_sha256'],image_sha]
            pid = 'position_'+fingerprint(identity)
            payload = {'kind':'fla_frame', 'precision':'timeline_exact', 'timeline_id':timeline['id'],
                       'timeline_kind':timeline['kind'], 'timeline_name':timeline['name'],
                       'frame_index0':frame['frame_index0'], 'frame_count':timeline['frame_count'],
                       'image_size':size, 'image_sha256':image_sha, 'cache':pid+'.png',
                       'coordinates':'symbol_export_pixels' if timeline['kind']=='symbol' else 'stage_export_pixels',
                       'render_scope':timeline['kind'], 'renderer':copy.deepcopy(result['renderer']),
                       'exporter_sha256':request['exporter_sha256'], 'export_ref':export_id,
                       'receipt_sha256':fingerprint(result), 'source_copy_sha256':request['source_sha256'],
                       'quality_flags':['empty_alpha'] if bounds is None else []}
            final = self.sources.cache/payload['cache']
            with self.sources.db() as db:
                existing = db.execute('SELECT payload FROM positions WHERE id=?',(pid,)).fetchone()
            if existing:
                old = json.loads(existing['payload'])
                require(old['image_sha256'] == image_sha, '同位置图像冲突。')
            if not final.exists() or media.sha_file(final) != image_sha:
                temp = self.sources.cache/(new_id('character_image')+'.png')
                temp.write_bytes(raw); os.replace(temp,final)
            with self.sources.db() as db:
                db.execute('INSERT OR IGNORE INTO positions VALUES(?,?,?,?,?)',
                           (pid,request['file_id'],request['version_id'],dumps(payload),now()))
            candidate = self.dataset.candidate(pid,request['set_id'])
            if candidate is None:
                candidate = self.dataset.decide(pid,'undecided',set_id=request['set_id'],actor=request['actor'],
                    evidence={'kind':'asset','method':'native_fla_render','export_ref':export_id,
                              'character_completeness':'unconfirmed'})
            positions.append(pid); candidates.append(candidate['id'])
            if jid:self.sources._progress(jid,index+1,len(prepared))
        result = {'export_id':export_id,'position_ids':positions,'candidate_ids':candidates,
                  'note':'画面已加入 M02 待判断；角色完整性、身份及姿态均未自动审核。'}
        _atomic_json(directory/'accepted.json',result)
        return result

    def queue_export(self, file_id, timeline_id, start=1, stop=None, step=1, *, actor='本机用户', set_id='set_inbox'):
        _,_,version = self._source(file_id)
        # Validate and freeze the exact source/timeline/range before queueing.
        bundle = self.prepare_export(file_id,timeline_id,start=start,stop=stop,step=step,actor=actor,set_id=set_id,
                                     version_id=version['id'])
        return self.sources.queue('character_fla', {'export_id':bundle['export_id']}, 'character_fla:'+bundle['export_id'])

    def execute(self, export_id, *, jid=None):
        # A failed native attempt is immutable. The job keeps its original id;
        # retry links select a new copy and request without losing the failure.
        seen = set()
        frozen = ('file_id', 'version_id', 'source_sha256', 'operation', 'timeline', 'frames0', 'actor', 'set_id')
        while True:
            require(export_id not in seen, '工程导出重试链出现循环，不能继续执行。')
            seen.add(export_id)
            directory, request = self._request(export_id)
            retry_path = directory/'retry.json'
            if not retry_path.exists():
                break
            link = load_json(retry_path)
            require(link.get('previous_export_id') == export_id and
                    link.get('request_sha256') == request['request_sha256'], '工程导出重试链接与原请求不匹配。')
            child_id = safe_id(link['export_id'])
            _, child = self._request(child_id)
            require(child.get('previous_export_id') == export_id and
                    all(child.get(key) == request.get(key) for key in frozen), '工程导出重试改变了原素材、时间轴或帧范围。')
            export_id = child_id

        result_path = directory/'result.json'
        if result_path.is_file():
            result = load_json(result_path)
            if isinstance(result, dict) and result.get('state') == 'failed':
                require(result.get('schema_version') == SCHEMA and result.get('export_id') == export_id and
                        result.get('request_sha256') == request['request_sha256'] and
                        result.get('operation') == request['operation'] and result.get('copy_uri') == request['copy_uri'],
                        '失败回执与原请求不匹配；不会重新投递。')
                self.sources._checkpoint()
                # The original must still represent this exact frozen version.
                self._source(request['file_id'], request['version_id'])
                child_id = new_id('character_export')
                child_dir = self.root/child_id
                child_dir.mkdir(parents=True, exist_ok=False)
                shutil.copyfile(directory/'source.fla', child_dir/'source.fla')
                require(media.sha_file(child_dir/'source.fla') == request['source_sha256'], '重试副本指纹不符。')
                (child_dir/'frames').mkdir()
                # A corrected exporter may be used, while its exact source is frozen again.
                template = (Path(__file__).parents[1]/'source_catalog/character_export.jsfl').read_text(encoding='utf-8')
                require(template.count('__PONY_CHARACTER_REQUEST__') == 1, '原生导出模板占位符无效')
                (child_dir/'exporter.jsfl').write_text(template, encoding='utf-8')
                child = copy.deepcopy(request)
                child.update(export_id=child_id, previous_export_id=export_id,
                    copy_uri=(child_dir/'source.fla').as_uri(), output_uri=(child_dir/'frames').as_uri()+'/',
                    result_uri=(child_dir/'result.json').as_uri(), created_at=now(),
                    exporter_sha256=hashlib.sha256(template.encode()).hexdigest())
                child.pop('request_sha256', None)
                child['request_sha256'] = fingerprint(child)
                _atomic_json(child_dir/'request.json', child)
                (child_dir/'export.jsfl').write_text(template.replace('__PONY_CHARACTER_REQUEST__',
                    json.dumps(child, ensure_ascii=True)), encoding='utf-8')
                _atomic_json(retry_path, {'previous_export_id':export_id, 'export_id':child_id,
                    'request_sha256':request['request_sha256'], 'created_at':now()})
                export_id, directory, request = child_id, child_dir, child
                result_path = directory/'result.json'

        if not result_path.exists():
            self.renderer.run({'export_id':export_id, 'script_path':str(directory/'export.jsfl'),
                               'result_path':str(result_path), 'request':request}, self.sources._checkpoint)
        # A failure from this attempt is reported now. Only a subsequent explicit
        # job retry may prepare the next attempt; this call cannot loop on failures.
        return self.accept_export(export_id,jid=jid)

    def positions(self, file_id, timeline_id=None):
        file = self.sources.file(file_id)
        with self.sources.db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM positions WHERE file_id=? AND version_id=?',
                                               (file_id,file['version_id']))]
        for row in rows:row['payload'] = json.loads(row['payload'])
        return sorted((r for r in rows if r['payload']['kind']=='fla_frame' and
                       (timeline_id is None or r['payload']['timeline_id']==timeline_id)),
                      key=lambda r:(r['payload']['timeline_id'],r['payload']['frame_index0'],r['created']))
