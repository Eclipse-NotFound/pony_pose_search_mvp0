"""Bounded, read-only timeline inventory. Stored XML is not a character renderer.

Identifiers preserve exact Animate library names; suggestions only prioritize
inspection. No layer or symbol name is treated as proof of a complete character.
"""
import os
from pathlib import Path, PurePosixPath
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

from multispecies.catalog import DataError, require
from .media import checkpoint

MAX_MEMBER = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_MEMBERS = 50000
MAX_FRAMES = 10000000
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _name(value):
    """Validate archive paths, even though nothing is extracted."""
    value = value.replace('\\', '/')
    require(value and '\x00' not in value and ':' not in value and not value.startswith('/'),
            'FLA/XFL 包含危险成员路径')
    require(all(p not in {'', '.', '..'} for p in value.rstrip('/').split('/')),
            'FLA/XFL 包含危险成员路径')
    require(not PurePosixPath(value).is_absolute(), 'FLA/XFL 包含绝对成员路径')
    return value


def _wanted(name):
    return name == 'DOMDocument.xml' or (name.startswith('LIBRARY/') and name.lower().endswith('.xml'))


def _structural_name(name):
    name = name.casefold()
    return name == 'domdocument.xml' or (name.startswith('library/') and name.endswith('.xml'))


def _xml(raw, expected):
    require(len(raw) <= MAX_MEMBER, 'FLA/XFL XML 超过读取上限')
    declarations = raw.replace(b'\x00', b'').upper()
    require(b'<!DOCTYPE' not in declarations and b'<!ENTITY' not in declarations,
            '不读取含外部声明的工程 XML')
    try:
        node = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DataError('工程 XML 无法解析') from exc
    for child in node.iter():
        child.tag = child.tag.rsplit('}', 1)[-1]
    require(node.tag == expected, f'未找到有效的 {expected}')
    return node


def _remember(seen, name, *, allow_metadata_repeat=False):
    # Windows cannot distinguish case-only XFL paths reliably.
    key = name.rstrip('/').casefold()
    # Adobe repeats mimetype/project descriptors in valid local-record files.
    # They are never read, extracted or executed. Structural XML must be unique.
    require(key not in seen or (allow_metadata_repeat and not _structural_name(name)),
            'FLA/XFL 包含重复成员路径：'+name)
    seen.add(key)
    require(len(seen) <= MAX_MEMBERS, 'FLA/XFL 成员数量超过读取上限')


def _xfl(path):
    root = path.resolve()
    found, seen, total = {}, set(), 0
    for directory, dirs, files in os.walk(path, followlinks=False):
        checkpoint()
        for basename in dirs + files:
            child = Path(directory)/basename
            require(not child.is_symlink() and not getattr(child, 'is_junction', lambda: False)(),
                    'XFL 工程包含链接')
            require(child.resolve().is_relative_to(root), 'XFL 成员离开工程目录')
            name = _name(child.relative_to(path).as_posix())
            _remember(seen, name)
            if basename not in files or not _wanted(name):
                continue
            require(child.stat().st_size <= MAX_MEMBER, 'XFL XML 超过读取上限')
            with child.open('rb') as stream:
                raw = stream.read(MAX_MEMBER+1)
            require(len(raw) <= MAX_MEMBER, 'XFL XML 超过读取上限')
            total += len(raw)
            require(total <= MAX_TOTAL, 'XFL XML 总量超过读取上限')
            found[name] = raw
    return found, 'xfl'


def _standard_zip(path):
    # Only constructor failure permits Adobe's local-record fallback. A damaged
    # ordinary ZIP must not bypass its CRC/name checks by being retried loosely.
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return None
    found, seen, total = {}, set(), 0
    try:
        with archive:
            require(len(archive.infolist()) <= MAX_MEMBERS, 'FLA 成员数量超过读取上限')
            for info in archive.infolist():
                checkpoint()
                name = _name(info.filename)
                _remember(seen, name, allow_metadata_repeat=True)
                require(not info.flag_bits & 1, '不支持加密 FLA 成员')
                mode = info.external_attr >> 16
                require(mode & 0o170000 != 0o120000, 'FLA 包含链接成员')
                if not _wanted(name):
                    continue
                require(info.file_size <= MAX_MEMBER and info.compress_size <= MAX_MEMBER,
                        'FLA XML 超过读取上限')
                require(info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED},
                        'FLA XML 压缩方式暂不支持')
                total += info.file_size
                require(total <= MAX_TOTAL, 'FLA XML 总量超过读取上限')
                with archive.open(info) as stream:
                    raw = stream.read(MAX_MEMBER+1)
                require(len(raw) == info.file_size, 'FLA XML 大小不匹配')
                found[name] = raw
    except (zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        raise DataError('FLA ZIP 校验失败') from exc
    return found, 'zip_xml'


def _local_zip(path):
    found, seen, total, member_count = {}, set(), 0, 0
    size = path.stat().st_size
    with path.open('rb') as stream:
        while True:
            checkpoint()
            signature = stream.read(4)
            if signature != b'PK\x03\x04':
                # Adobe's nonstandard directory is not evaluated or executed.
                break
            member_count += 1
            require(member_count <= MAX_MEMBERS, 'FLA 成员数量超过读取上限')
            header = stream.read(26)
            require(len(header) == 26, 'FLA 本地记录头不完整')
            _, flags, method, _, _, crc, packed_size, raw_size, nl, xl = struct.unpack('<HHHHHIIIHH', header)
            require(not flags & 9, 'FLA 本地记录含加密或未支持的数据描述符')
            require(stream.tell()+nl+xl+packed_size <= size, 'FLA 本地记录超出文件范围')
            try:
                name = _name(stream.read(nl).decode('utf-8' if flags & 0x800 else 'cp437'))
            except UnicodeDecodeError as exc:
                raise DataError('FLA 成员路径编码无效') from exc
            _remember(seen, name, allow_metadata_repeat=True)
            stream.seek(xl, 1)
            if not _wanted(name):
                stream.seek(packed_size, 1)
                continue
            require(packed_size <= MAX_MEMBER and raw_size <= MAX_MEMBER, 'FLA XML 超过读取上限')
            total += raw_size
            require(total <= MAX_TOTAL, 'FLA XML 总量超过读取上限')
            require(method in {0, 8}, 'FLA XML 压缩方式暂不支持')
            packed = stream.read(packed_size)
            if method == 8:
                decoder = zlib.decompressobj(-15)
                try:
                    raw = decoder.decompress(packed, MAX_MEMBER+1)
                except zlib.error as exc:
                    raise DataError('FLA XML 解压失败') from exc
                require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
                        'FLA XML 压缩记录不完整或过大')
            else:
                raw = packed
            require(len(raw) == raw_size and zlib.crc32(raw) == crc, 'FLA XML 大小或 CRC 不匹配')
            found[name] = raw
    return found, 'zip_local_records'


def _timeline(node, *, identity, kind, name, member):
    layers = node.findall('./layers/DOMLayer')
    end, starts, refs, labels, tween_types = 0, set(), set(), [], set()
    for layer in layers:
        for frame in layer.findall('./frames/DOMFrame'):
            try:
                start, duration = int(frame.get('index', '0')), int(frame.get('duration', '1'))
            except ValueError as exc:
                raise DataError('工程关键帧范围无效') from exc
            require(start >= 0 and duration > 0 and start+duration <= MAX_FRAMES, '工程关键帧范围无效或超过上限')
            end = max(end, start+duration)
            starts.add(start)
            if frame.get('name'):
                labels.append({'index0': start, 'name': frame.get('name'), 'type': frame.get('labelType')})
            if frame.get('tweenType'):
                tween_types.add(frame.get('tweenType'))
            refs.update(e.get('libraryItemName') for e in frame.findall('.//DOMSymbolInstance') if e.get('libraryItemName'))
    return {'id': identity, 'kind': kind, 'name': name, 'frame_count': end, 'member': member,
            'layer_count': len(layers), 'stored_key_starts0': sorted(starts), 'references': sorted(refs),
            'labels': labels, 'tween_types': sorted(tween_types), 'suggested': kind == 'scene',
            'reason': '主场景，可先渲染后筛选完整角色' if kind == 'scene' else '库元件；可选择渲染，尚未确认是否完整角色'}


def inspect_structure(path):
    """Return exact selectable timelines without interpreting playback or identity.

    OLE is an explicit native-inspection request, not an empty successful scan.
    Modern FLA/XFL member errors raise DataError; originals are never written.
    """
    path = Path(path)
    if path.is_dir():
        raw, container = _xfl(path)
    else:
        with path.open('rb') as stream:
            if stream.read(8) == OLE_MAGIC:
                return {'container': 'ole', 'timelines': [], 'native_inspect': True,
                        'warnings': ['旧版 OLE FLA 需要 Animate 原生检查时间轴；尚未渲染。']}
        result = _standard_zip(path)
        raw, container = result if result is not None else _local_zip(path)
    require('DOMDocument.xml' in raw, 'FLA/XFL 中没有可核验的 DOMDocument.xml')
    document = _xml(raw['DOMDocument.xml'], 'DOMDocument')
    timelines = [_timeline(node, identity=f'scene:{i}', kind='scene', name=node.get('name', f'场景 {i+1}'),
                           member='DOMDocument.xml')
                 for i, node in enumerate(document.findall('./timelines/DOMTimeline'))]
    for i, timeline in enumerate(timelines):
        timeline['index0'] = i
    scene_refs = {ref for t in timelines for ref in t['references']}
    warnings = ['仅读取存储结构；未确认角色身份、完整性、实际播放或补间画面。']
    seen_names, included = set(), set()
    for include in document.findall('./symbols/Include'):
        member = 'LIBRARY/'+_name(include.get('href', ''))
        require(member.casefold() not in included, '工程包含重复的库元件引用路径')
        included.add(member.casefold())
        require(member in raw, '工程引用的库元件 XML 缺失：'+member)
        item = _xml(raw[member], 'DOMSymbolItem')
        name = item.get('name')
        require(isinstance(name, str) and name.strip() and '\x00' not in name, '库元件没有有效的精确名称')
        require(name not in seen_names, '工程包含重复库元件名称：'+name)
        seen_names.add(name)
        nodes = item.findall('./timeline/DOMTimeline')
        require(len(nodes) <= 1, '库元件包含多个时间轴，不能精确定位：'+name)
        if not nodes:
            warnings.append('库元件无可用时间轴：'+name)
            continue
        timeline = _timeline(nodes[0], identity='symbol:'+name, kind='symbol', name=name, member=member)
        timeline['direct_scene_reference'] = name in scene_refs
        timeline['suggested'] = name in scene_refs and len(timeline['references']) >= 2
        if timeline['suggested']:
            timeline['reason'] = '场景直接使用的复合元件；优先预览，仍需确认是否完整角色'
        timelines.append(timeline)
    missing = sorted({ref for t in timelines for ref in t['references']} - seen_names)
    if missing:
        warnings.append('部分元件引用未找到对应时间轴，渲染前需核验：'+', '.join(missing[:20]))
    return {'container': container, 'timelines': timelines, 'warnings': warnings,
            'width': document.get('width'), 'height': document.get('height'),
            'frame_rate': document.get('frameRate'), 'native_inspect': False,
            'numbering': '帧范围内部从 0 开始，界面显示从 1 开始；symbol id 保留精确库名'}
