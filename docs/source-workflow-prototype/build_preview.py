"""Build the offline workflow demo. Original assets are only read; no library API is used."""
import base64
import hashlib
import io
import json
import subprocess
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
ROOT = Path(r'D:\活\AE\素材\泄露素材')
BIN = Path(r'C:\Users\hello\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin')
CACHE = PROJECT / 'experiments/source_workflow_preview_20261012'
CACHE.mkdir(parents=True, exist_ok=True)

def run(exe, args):
    return subprocess.check_output([str(BIN / exe), *args], stderr=subprocess.PIPE)

def picture(path):
    im = Image.open(path).convert('RGB')
    im.thumbnail((800, 450))
    out = io.BytesIO()
    im.save(out, 'JPEG', quality=83)
    return 'data:image/jpeg;base64,' + base64.b64encode(out.getvalue()).decode()

images, clips, frames, assets, probes = {}, {}, {}, [], {}
for aid, rel, character, indices in [
    ('discord', '925/ReviewQT/MLP925_020.mp4', '无序', None),
    ('spike', '925/ReviewQT/MLP925_016.mp4', '穗龙 / 无序', [0, 114, 229]),
    ('tirek', '925/ReviewQT/MLP925_012.mp4', '提雷克', [0, 31]),
    ('twilight', '813/ReviewQT/MLP813_002.mp4', '暮光闪闪', [0]),
    ('mov', '214/SceneSetups/MLP214_092.mov', '小马群像', [0]),
]:
    path = ROOT / rel
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    raw = json.loads(run('ffprobe.exe', ['-v', 'error', '-select_streams', 'v:0', '-show_streams', '-show_frames', '-show_entries', 'stream=index,codec_name,width,height,time_base,nb_frames,avg_frame_rate:frame=pts,best_effort_timestamp_time', '-of', 'json', str(path)]))
    stream, ff = raw['streams'][0], raw['frames']
    indices = list(range(len(ff))) if indices is None else indices
    dest = CACHE / aid
    dest.mkdir(exist_ok=True)
    if aid == 'discord':
        run('ffmpeg.exe', ['-v', 'error', '-y', '-i', str(path), '-map', '0:v:0', '-vf', 'scale=800:-2', '-q:v', '3', '-fps_mode', 'passthrough', '-start_number', '0', str(dest / '%05d.jpg')])
    else:
        for n in indices:
            run('ffmpeg.exe', ['-v', 'error', '-y', '-i', str(path), '-map', '0:v:0', '-vf', f'select=eq(n\\,{n}),scale=800:-2', '-frames:v', '1', '-q:v', '3', str(dest / f'{n:05d}.jpg')])
    for n in indices:
        images[f'{aid}-{n}'] = picture(dest / f'{n:05d}.jpg')
    frames[aid] = [{'n': n, 'pts': ff[n].get('pts'), 'seconds': ff[n]['best_effort_timestamp_time'], 'image': f'{aid}-{n}'} for n in indices]
    if aid in ('discord', 'spike', 'tirek', 'twilight'):
        clips[aid] = 'data:video/mp4;base64,' + base64.b64encode(path.read_bytes()).decode()
    representative = {'discord': 26, 'spike': 114, 'tirek': 31}.get(aid, 0)
    assets.append(dict(id=aid, rel=rel, name=path.name, format=path.suffix[1:].upper(), kind='video', character=character, episode=rel.split('/')[0], bytes=path.stat().st_size, thumb=f'{aid}-{representative}', defaultFrame=representative, frames=len(ff), width=stream['width'], height=stream['height'], timebase=stream['time_base'], stream=stream['index'], sha256=digest))
    probes[aid] = dict(path=str(path), sha256=digest, stream=stream, frame_count=len(ff), samples=frames[aid], source_unchanged=digest==hashlib.sha256(path.read_bytes()).hexdigest())

for aid, rel, kind, character, thumb, extra in [
    ('fla-discord', '925/scenesetups/MLP925_020.fla', 'project', '角色尚未核对', None, {'container':'ZIP / XML', 'mainFrames':106, 'scene':'Scene 1', 'related':'discord'}),
    ('fla-spike', '925/scenesetups/MLP925_016.fla', 'project', '角色尚未核对', None, {'container':'ZIP / XML', 'related':'spike'}),
    ('fla-tirek', '925/scenesetups/MLP925_012.fla', 'project', '角色尚未核对', None, {'container':'ZIP / XML', 'related':'tirek'}),
    ('fla-twilight', '813/scenesetups/MLP813_002.fla', 'project', '角色尚未核对', None, {'container':'ZIP / XML', 'related':'twilight'}),
    ('fla-old', '214/SceneSetups/MLP214_092.fla', 'project', '角色尚未核对', None, {'container':'旧版 OLE', 'related':'mov'}),
    ('jpg', '214/SceneSetups/MLP214_092.jpg', 'image', '小马群像', 'party', {}),
    ('swf', '214/SceneSetups/MLP214_092.swf', 'animation', '角色尚未核对', None, {}),
]:
    path=ROOT/rel
    if aid=='jpg':
        images['party']=picture(path)
        extra['dimensions']='3600 × 2025'
    assets.append(dict(id=aid, rel=rel, name=path.name, format=path.suffix[1:].upper(), kind=kind, character=character, episode=rel.split('/')[0], bytes=path.stat().st_size, thumb=thumb, **extra))

payload = dict(root=str(ROOT), assets=assets, images=images, clips=clips, frames=frames, built='2026-10-12')
template=(HERE/'preview.template.html').read_text(encoding='utf-8')
assert template.count('__EMBEDDED_FIXTURES__')==1
out=template.replace('__EMBEDDED_FIXTURES__', json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</','<\\/'))
(HERE/'index.html').write_text(out, encoding='utf-8')
(CACHE/'media-evidence.json').write_text(json.dumps(probes, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'html':str(HERE/'index.html'),'bytes':len(out.encode()),'assets':len(assets),'embedded_images':len(images),'frames_in_main_clip':len(frames['discord']),'all_sources_unchanged':all(p['source_unchanged'] for p in probes.values())},ensure_ascii=False))
