"""Run the shipped application end to end with synthetic, isolated media."""
import json
from pathlib import Path
import sys
import time


def run(destination):
    import tkinter as tk
    from PIL import Image, ImageDraw
    from app_runtime import resource_root, default_library, remember_library, user_home
    from control_center import ControlCenter
    from source_catalog import media

    destination.mkdir(parents=True, exist_ok=False)
    project = resource_root()
    root = tk.Tk(); root.withdraw()
    app = None
    try:
        app = ControlCenter(root, project, destination/'测试资料库', startup_check=True)
        ctx = app.project_context
        assert ctx.library.records() == []
        for module in ('M01', 'M02', 'M03', 'M04', 'M05', 'M06', 'M07', 'M08', 'M09'):
            app.native_workbench.open_module(module)
            root.update()
        pic = Image.new('RGB', (96, 64), 'white')
        ImageDraw.Draw(pic).line((12, 32, 80, 32), fill='purple', width=10)
        image = destination/'合成 图片.png'; pic.save(image)
        # The bundled media tools intentionally omit PNG; images are handled by Pillow.
        bmp = destination/'编码输入.bmp'; pic.save(bmp)
        video = destination/'合成 视频.mp4'
        media.run('ffmpeg', ['-y', '-loop', '1', '-i', bmp, '-t', '1', '-r', '5',
                             '-c:v', 'mpeg4', '-pix_fmt', 'yuv420p', video])
        media.proxy(video, 0, destination/'播放预览.mp4')
        ctx.sources.add_inputs([str(image), str(video)])
        for _ in range(300):
            files = ctx.sources.list_files()['items']
            if len(files) == 2 and all(f['state'] == 'ready' for f in files):
                break
            root.update(); time.sleep(.1)
        records = []
        for file in ctx.sources.list_files()['items']:
            assert file['state'] == 'ready', file
            position = ctx.sources.create_position(file['id'], **({'ordinal0': 2} if file['format'] == 'MP4' else {}))
            record = ctx.service.import_observation(position_id=position['id'], roi=[0, 0, 96, 64],
                form_ref='twilight.unicorn@1', request_id='smoke_'+file['id'])['record']
            record = ctx.library.edit(record['observation_id'], record['annotation']['id'],
                {'parts': {'core': {'presence': 'present'}},
                 'directions': {'core.head': {'value': [1, 0], 'visibility': 'visible'}}},
                actor='release smoke test', review={'status': 'approved', 'targets': ['parts.core', 'directions.core.head']})
            location = ctx.service.describe(record)
            assert Path(location['path']).is_file()
            if file['format'] == 'MP4':
                assert location['position']['presentation_ordinal0'] == 2
            records.append(record)
        assert len(records) == 2
        query = ctx.poses.prepare_query(records[0]['observation_id'])
        result = ctx.poses.search(query['id'])
        assert result['results'], result
        exported = ctx.poses.export(result['run_id'], include_html=True)
        assert all(Path(exported[k]).is_file() for k in ('html', 'json', 'csv'))
        import workflow.character_fla as fla
        assert (Path(fla.__file__).parents[1]/'source_catalog/character_export.jsfl').is_file()
        remember_library(ctx.library.root)
        assert default_library(project) == ctx.library.root
        assert user_home() in ctx.characters.renderer.state_root.parents
        assert str(Path(sys.executable).resolve()) not in ctx.models.runtimes()
        app.native_workbench.refresh_records()
        root.update()
        report = {'status': 'passed', 'frozen': bool(getattr(sys, 'frozen', False)),
                  'modules': 9, 'formats': ['PNG', 'MP4'], 'observations': len(records),
                  'video_frame': 3, 'search_results': len(result['results']),
                  'ffmpeg': media.binary('ffmpeg'), 'ffprobe': media.binary('ffprobe'),
                  'resource_root': str(project), 'library': str(ctx.library.root),
                  'fla_template': 'present; native Animate export not run',
                  'exports': {k: str(v) for k, v in exported.items()}}
        (destination/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        if app:
            app.native_workbench.close()
            app.project_context.close()
        root.destroy()
