"""An offline review page, without changing or approving any labels."""
import sys
sys.dont_write_bytecode = True
import base64
import io
import json
import os
from PIL import Image
from direction_scaling_select import OUT
from direction_pilot_data import ROOT, EDGES, read, write, sha
from direction_expanded_preview import POINT_NAMES


def main():
    data=read(OUT/'dataset.json'); frames=[]
    for r in data['records']:
        if r['source']!='agent_scaling_visual_20261009': continue
        with Image.open(ROOT/r['image']) as im:
            im=im.convert('RGB'); im.thumbnail((680,680)); buf=io.BytesIO()
            im.save(buf,format='JPEG',quality=78,optimize=True)
        sec=int(r['frame_id'][8:14])
        frames.append(dict(id=r['frame_id'],time=f'{sec//60}:{sec%60:02}',size=r['size'],points=r['points'],note=r['notes'],
            middle='n203' in r['regimes'],directions=sum(v['available'] for v in r['directions'].values()),
            original=os.path.relpath(ROOT/r['image'],OUT).replace('\\','/'),
            image='data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode('ascii')))
    template=(ROOT/'scripts/ai/direction_scaling_review.template.html').read_text(encoding='utf-8')
    payload=json.dumps(dict(frames=frames,pointNames=POINT_NAMES,edges=EDGES),ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    assert template.count('__DATA__')==1 and len(frames)==200
    path=OUT/'annotation-review.html'; path.write_text(template.replace('__DATA__',payload),encoding='utf-8')
    write(OUT/'review_manifest.json',dict(frames=200,path=path.relative_to(ROOT).as_posix(),sha256=sha(path),
        note='Read-only visual browser; no review/approval status is changed by viewing. Original-size crop links remain local.'))
    print(path, path.stat().st_size)


if __name__=='__main__': main()
