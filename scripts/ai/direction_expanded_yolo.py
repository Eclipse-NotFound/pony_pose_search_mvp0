"""Practical YOLOv8-Pose reference, isolated from the production model.

Unlike the matched ResNet arms this has different pretraining and resolution.
Do not interpret its comparison as a causal test of the output representation.
"""
import sys
sys.dont_write_bytecode=True
import os
import shutil
import time
from pathlib import Path
from direction_expanded_data import ROOT,OUT,EDGES,NAMES,read,write,sha
os.environ['YOLO_CONFIG_DIR']=str(OUT/'yolo_config')
os.environ['MPLCONFIGDIR']=str(OUT/'mpl_config')
os.environ['YOLO_AUTOINSTALL']='false'
for config_dir in ['yolo_config','mpl_config']:
    (OUT/config_dir).mkdir(parents=True,exist_ok=True)


def export_dataset(data):
    dest=OUT/'yolo_dataset';manifest=[]
    for r in data['records']:
        if r['split'] not in ['train','val']:continue
        split=r['split'];copies=2 if split=='train' and r['source']=='human_official' else 1
        for copy in range(copies):
            name=f"{r['frame_id']}_{copy}"
            image=dest/split/'images'/f'{name}.png';label=dest/split/'labels'/f'{name}.txt'
            image.parent.mkdir(parents=True,exist_ok=True);label.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/r['image'],image)
            coords=[];w,h=r['size']
            for p in r['points']:
                coords.extend([0,0,0] if p is None else [p[0]/w,p[1]/h,2])
            label.write_text(' '.join(str(v) for v in [0,.5,.5,1.,1.,*coords])+'\n',encoding='ascii')
            manifest.append(dict(file=str(image.relative_to(OUT)),frame_id=r['frame_id'],split=split,source=r['source']))
    config=dict(path=str(dest.resolve()),train='train/images',val='val/images',names=['twilight'],kpt_shape=[21,3],flip_idx=list(range(21)))
    write(dest/'data.yaml',config);write(OUT/'yolo_export_manifest.json',dict(records=manifest,note='Only human TRAIN images duplicated to reproduce the 1:0.5 relative label weights; 103 unique training crops, 135 training entries; evaluation never duplicated.'))
    return dest/'data.yaml'


def evaluate_yolo(model,rows):
    import numpy as np
    import torch
    from direction_expanded_train import prepare,metric,SIZE
    from direction_pilot import directions_from_points
    from direction_yolo_raw_predictor import RawPosePredictor
    allp=[];allz=[]
    for r in rows:
        result=model.predict(source=str(ROOT/r['image']),imgsz=320,conf=.001,max_det=1,verbose=False,device=0,predictor=RawPosePredictor)[0]
        w,h=r['size'];scale=SIZE/max(w,h);left=(SIZE-round(w*scale))//2;top=(SIZE-round(h*scale))//2
        p=np.zeros((21,2),dtype=np.float32);q=np.zeros(21,dtype=np.float32)
        if result.boxes is not None and len(result.boxes) and result.keypoints is not None:
            raw=result.keypoints.data[0].detach().cpu().numpy();p=raw[:,:2];q=raw[:,2]
        p=((p+.5)*scale+np.array([left,top]))/SIZE
        allp.append(p);allz.append([min(q[a],q[b]) for a,b in EDGES])
    p=torch.tensor(np.stack(allp),dtype=torch.float32)
    prob=torch.tensor(np.stack(allz),dtype=torch.float32)
    vectors=directions_from_points(p)
    # Missing detections/zero-confidence keypoints count as failed directions,
    # rather than disappearing from the ground-truth mask.
    vectors=torch.where((prob>0)[...,None],vectors,torch.zeros_like(vectors))
    out=dict(p=p,v=vectors,z=torch.logit(prob.clamp(1e-6,1-1e-6)),hm=None)
    tt=[prepare(r)[1] for r in rows]
    t={k:torch.tensor(np.stack([v[k] for v in tt]),dtype=torch.float32) for k in ['p','pm','v','dm','weight']}
    return dict(metrics=metric(out,t),frame_ids=[r['frame_id'] for r in rows],vectors=vectors.tolist(),availability=prob.tolist(),points_letterbox=p.tolist())


def main():
    import torch
    from ultralytics import YOLO, settings
    torch.set_num_threads(4)
    settings.update({k:False for k in ['sync','hub','wandb','mlflow','neptune','clearml','comet','tensorboard','dvc','raytune','vscode_msg'] if k in settings})
    folder=OUT/'runs/yolo_reference_s11'
    if (folder/'result.json').exists():raise RuntimeError('Reference run already exists')
    data=read(OUT/'dataset.json')
    for path,h in data['source_hashes'].items():assert sha(ROOT/path)==h,path
    config=export_dataset(data);weights=OUT/'weights/yolov8n-pose.pt'
    if not weights.exists():raise FileNotFoundError('Download official YOLOv8n-Pose weights into '+str(weights))
    start=time.perf_counter();model=YOLO(str(weights))
    model.train(data=str(config),epochs=80,imgsz=320,batch=8,device=0,workers=0,seed=11,
                project=str(OUT/'yolo_runs'),name='reference_s11',exist_ok=False,pretrained=True,
                optimizer='AdamW',lr0=.001,lrf=.01,weight_decay=.001,patience=80,
                mosaic=0,mixup=0,degrees=0,translate=0,scale=0,shear=0,perspective=0,
                fliplr=.5,flipud=0,hsv_h=0,hsv_s=0,hsv_v=.15,amp=False,plots=False,
                save=True,val=True,cache=True,verbose=False)
    best=Path(model.trainer.best);chosen=YOLO(str(best));folder.mkdir(parents=True,exist_ok=True)
    shutil.copy2(best,folder/'checkpoint.pt')
    result=dict(arm='yolov8n_pose_reference',regime='expanded103',seed=11,train_images=103,
                seconds=time.perf_counter()-start,selection='Ultralytics validation fitness, not final test',
                limitations='Different backbone, COCO pretraining and 320px inputs; practical reference only. One seed, unlike the three-seed matched arms.',
                encoder_weights_sha256=sha(weights),dataset_sha256=sha(OUT/'dataset.json'),evaluations={})
    for split in ['test','challenge_agent_reference']:
        result['evaluations'][split]=evaluate_yolo(chosen,[r for r in data['records'] if r['split']==split])
    for path,h in data['source_hashes'].items():assert sha(ROOT/path)==h,path
    write(folder/'result.json',result)
    print({s:r['metrics']['mae_deg'] for s,r in result['evaluations'].items()},flush=True)


if __name__=='__main__':main()
