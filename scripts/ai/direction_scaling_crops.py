"""Propose crops from existing full frames; all proposals require visual screening."""
import sys
sys.dont_write_bytecode=True
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'experiments/direction_scaling_20261009'
os.environ['YOLO_CONFIG_DIR']=str(OUT/'yolo_settings')
from PIL import Image
import torch
from ultralytics import YOLO, settings
from direction_pilot_data import read,write,sha
from direction_scaling_select import sheets

def main():
    torch.set_num_threads(4)
    settings.update({k:False for k in ['sync','hub','wandb','mlflow','neptune','clearml','comet','tensorboard','dvc','raytune','vscode_msg'] if k in settings})
    model_path=ROOT/'models/twilight_detector_v3/best.pt';model=YOLO(str(model_path))
    rows=read(OUT/'inventory.json')['detected_uncropped'];proposals=[]
    (OUT/'crops').mkdir(exist_ok=True)
    for offset in range(0,len(rows),8):
        rr=rows[offset:offset+8];ims=[Image.open(ROOT/r['image']).convert('RGB') for r in rr]
        outputs=model.predict(ims,imgsz=640,conf=.25,device=0,verbose=False)
        for r,im,p in zip(rr,ims,outputs):
            if not len(p.boxes):continue
            k=int(p.boxes.conf.argmax());box=p.boxes.xyxy[k].cpu().tolist();score=float(p.boxes.conf[k]);w,h=im.size
            # Small context margin. Review crops visually before annotating.
            x1,y1,x2,y2=box;dx=(x2-x1)*.04;dy=(y2-y1)*.04
            box=[max(0,int(x1-dx)),max(0,int(y1-dy)),min(w,round(x2+dx)),min(h,round(y2+dy))]
            path=OUT/'crops'/f"{r['frame_id']}.png";im.crop(box).save(path)
            proposals.append(dict(frame_id=r['frame_id'],image=path.relative_to(ROOT).as_posix(),original=r['image'],original_sha256=sha(ROOT/r['image']),box=box,detector_confidence=score))
        print(f'{offset+len(rr)}/{len(rows)}',flush=True)
    write(OUT/'crop_proposals.json',dict(detector=model_path.relative_to(ROOT).as_posix(),detector_sha256=sha(model_path),frames=proposals))
    sheets(proposals,'proposed-crops',columns=4,rows_per_page=4,cell_height=260)
    print('PROPOSED',len(proposals),flush=True)

if __name__=='__main__':main()
