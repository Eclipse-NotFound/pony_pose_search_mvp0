"""Inventory and contact sheets for the isolated annotation volume study."""
import sys
sys.dont_write_bytecode = True
import csv
from collections import Counter
from PIL import Image, ImageDraw
from direction_pilot_data import ROOT, read, write, sha

OUT = ROOT/'experiments/direction_scaling_20261009'
PREVIOUS = ROOT/'experiments/direction_expanded_20261009'

def sheets(rows, prefix, columns=4, rows_per_page=4, width=1280, cell_height=235):
    n=columns*rows_per_page
    for offset in range(0,len(rows),n):
        canvas=Image.new('RGB',(width,cell_height*rows_per_page),'#eeeeee');draw=ImageDraw.Draw(canvas)
        for j,r in enumerate(rows[offset:offset+n]):
            with Image.open(ROOT/r['image']) as raw:
                im=raw.convert('RGB');im.thumbnail((width//columns-12,cell_height-30))
            x=(j%columns)*(width//columns)+(width//columns-im.width)//2
            y=(j//columns)*cell_height+25
            canvas.paste(im,(x,y));draw.text(((j%columns)*(width//columns)+6,y-20),r['frame_id'],fill='black')
        canvas.save(OUT/f'{prefix}-{offset//n+1:02}.jpg',quality=92)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    previous=read(PREVIOUS/'dataset.json');used={r['frame_id'] for r in previous['records']}
    used_hashes={sha(ROOT/r['image']) for r in previous['records']};seen=set(used_hashes)
    crops=[]
    for p in sorted((ROOT/'crops/twilight_unicorn/s01/e15').glob('*.png')):
        fid=p.name[:19];sec=int(fid[8:14]);h=sha(p)
        if fid in used or 220<=sec<=410 or h in seen:continue
        seen.add(h);crops.append(dict(frame_id=fid,image=p.relative_to(ROOT).as_posix(),sha256=h))
    candidates=list(csv.DictReader((ROOT/'candidates/twilight_unicorn/s01/candidate_frames_twilight_unicorn_s01e15_ai.csv').open(encoding='utf-8-sig')))
    missing=[]
    for r in candidates:
        fid=r['frame_id'];sec=int(fid[8:14])
        if r['usable']!='1' or 220<=sec<=410 or fid in used:continue
        if (ROOT/f'crops/twilight_unicorn/s01/e15/{fid}_twilight_unicorn_001.png').exists():continue
        missing.append(dict(frame_id=fid,image=r['image_path']))
    write(OUT/'inventory.json',dict(eligible_crops=crops,detected_uncropped=missing,excluded_validation_seconds=[220,410],existing_records=len(previous['records'])))
    sheets(crops,'crop-candidates')
    sheets(missing,'full-candidates',columns=4,rows_per_page=5,cell_height=205)
    print(dict(crops=len(crops),detected_uncropped=len(missing),candidate_count=len(candidates),usable=Counter(r['usable'] for r in candidates)))
    print('crop times',[int(r['frame_id'][8:14]) for r in crops])
    print('full times',[int(r['frame_id'][8:14]) for r in missing])

if __name__=='__main__':main()
