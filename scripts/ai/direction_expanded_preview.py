"""Embed already-saved predictions in the literal comparison fragment."""
import sys
sys.dont_write_bytecode = True
import argparse
import base64
import io
import json
import math
import re
from pathlib import Path
from PIL import Image
from direction_expanded_data import ROOT, OUT, EDGES, NAMES, read, write

POINT_NAMES = ['头中心','头朝向参考','颈方向参考','前躯中心','后躯中心',
               '前腿1根','前腿1中','前腿1末','前腿2根','前腿2中','前腿2末',
               '后腿1根','后腿1膝','后腿1中','后腿1末','后腿2根','后腿2膝','后腿2中','后腿2末',
               '尾根','尾朝向参考']
DIRECTION_NAMES = ['头','颈','身体','尾巴','前腿1上段','前腿1下段','前腿2上段','前腿2下段',
                   '后腿1上段','后腿1中段','后腿1下段','后腿2上段','后腿2中段','后腿2下段']


def permutation(choice):
    # Same four WHOLE-leg permutations recorded by the scorer; all self-inverse.
    front, back = [(0,0),(1,0),(0,1),(1,1)][choice]
    p = list(range(21)); d = list(range(14))
    if front:
        p[5:11] = list(range(8,11))+list(range(5,8)); d[4:8] = [6,7,4,5]
    if back:
        p[11:19] = list(range(15,19))+list(range(11,15)); d[8:14] = [11,12,13,8,9,10]
    return p, d


def build(fragment):
    dataset = read(OUT/'dataset.json')
    runs = [read(p) for p in (OUT/'runs').glob('expanded103_*/result.json')]
    chosen = {name:min((r for r in runs if r['arm']==arm), key=lambda r:r['val_mae_deg'])
              for name, arm in [('keypoint','keypoint_heatmap'),('direction','direct_vector')]}
    yp = OUT/'runs/yolo_reference_s11/result.json'
    chosen['yolo'] = read(yp) if yp.exists() else None
    frames = []
    for r in dataset['records']:
        if r['split'] not in ['test','challenge_agent_reference']:
            continue
        w,h = r['size']; gt = [r['directions'][n]['vector'] for n in NAMES]
        with Image.open(ROOT/r['image']) as im:
            im = im.convert('RGB'); im.thumbnail((350,350))
            buf = io.BytesIO(); im.save(buf, format='JPEG', quality=60, optimize=True)
        frame = dict(id=r['frame_id'],reference='human' if r['source']=='human_official' else 'agent',
            width=w,height=h,image='data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode('ascii'),
            points=[None if p is None else [p[0]/w,p[1]/h] for p in r['points']],vectors=gt,models={})
        seconds = int(r['frame_id'][8:14])
        frame['label'] = ('人工参考' if frame['reference']=='human' else 'AI待审参考')+f' · 第24集 {seconds//60}:{seconds%60:02}'
        for name, result in chosen.items():
            if result is None:
                frame['models'][name] = None
                continue
            ev = result['evaluations'][r['split']]; i = ev['frame_ids'].index(r['frame_id'])
            pp, dp = permutation(ev['metrics']['matched_permutation'][i])
            vectors = [ev['vectors'][i][j] for j in dp]
            available = [ev['availability'][i][j] for j in dp]
            angles = [ev['metrics']['angles'][i][j] if gt[k] is not None else None for k,j in enumerate(dp)]
            # Verify permutation inversion against the reference directions.
            for v, g, angle in zip(vectors, gt, angles):
                if g is None:
                    continue
                n = math.hypot(*v)
                calc = 180 if n<1e-5 else math.degrees(math.acos(max(-1,min(1,v[0]*g[0]+v[1]*g[1]))))
                assert abs(calc-angle)<.1, (r['frame_id'],name,calc,angle)
            points = None
            if ev['points_letterbox'] is not None:
                scale=224/max(w,h); left=(224-round(w*scale))//2; top=(224-round(h*scale))//2
                points = [[((ev['points_letterbox'][i][j][0]*224-left)/scale-.5)/w,
                           ((ev['points_letterbox'][i][j][1]*224-top)/scale-.5)/h] for j in pp]
            frame['models'][name] = dict(points=points,vectors=vectors,angles=angles,
                mae=ev['metrics']['per_image'][i],extraAvailable=sum(a>=.5 and g is None for a,g in zip(available,gt)))
        frames.append(frame)
    summary = read(OUT/'summary.json')['rows']
    table = []
    for label,arm in [('关键点网络','keypoint_heatmap'),('直接向量网络','direct_vector')]:
        table.append(dict(label=label,**{regime:next(r['mae_deg'] for r in summary if r['arm']==arm and r['regime']==regime and r['split']=='test') for regime in ['base55','expanded103']}))
    if chosen['yolo'] is not None:
        table.append(dict(label='YOLO关键点（单次参照）',base55=None,
                          expanded103=chosen['yolo']['evaluations']['test']['metrics']['mae_deg']))
    data = dict(summary=table,frames=frames,pointNames=POINT_NAMES,names=DIRECTION_NAMES,edges=EDGES)
    compact = json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    source = fragment.read_text(encoding='utf-8')
    pattern = r'(<script type="application/json" id="pose-comparison-data">)[\s\S]*?(</script>)'
    source,n = re.subn(pattern, lambda m:m[1]+compact+m[2],source)
    assert n == 1 and len(source.encode('utf-8')) < 1_000_000
    fragment.write_text(source,encoding='utf-8',newline='\n')
    write(OUT/'preview_selection.json',dict(rule='lowest validation error only, not lowest test error',
        selected={k:None if v is None else dict(arm=v['arm'],seed=v['seed'],validation_mae=v.get('val_mae_deg')) for k,v in chosen.items()},
        reference_anchors='All direction-only arrows use reference positions; no position prediction attributed to the direct-vector model.',
        frames=len(frames),html_bytes=len(source.encode('utf-8')),fragment_path=str(fragment.resolve())))
    print('Preview:',len(frames),'images;',len(source.encode('utf-8')),'bytes',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('fragment',type=Path)
    build(parser.parse_args().fragment)
