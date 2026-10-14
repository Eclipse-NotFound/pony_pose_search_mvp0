"""Isolated frozen-feature comparison: coordinates, coordinates+angles, directions.

No official annotation/model/search file is written. Train/val/test is fixed by
direction_pilot_data.py. Validation selects epochs; test never selects settings.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import copy
import hashlib
import json
import math
import os
import random
import time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from direction_pilot_data import ROOT, OUT, EDGES, NAMES, read, write, sha, crop

os.environ.setdefault("TORCH_HOME",str(OUT/"weights"))
import torch
from torch import nn
from torch.nn import functional as F
torch.set_num_threads(4)

def permutations():
    points=[]; directions=[]
    for front,back in [(0,0),(1,0),(0,1),(1,1)]:
        p=list(range(21));d=list(range(14))
        if front:p[5:11]=list(range(8,11))+list(range(5,8));d[4:8]=[6,7,4,5]
        if back:p[11:19]=list(range(15,19))+list(range(11,15));d[8:14]=[11,12,13,8,9,10]
        points.append(p);directions.append(d)
    return np.array(points),np.array(directions)

P_PERM,D_PERM=permutations()

def directions_from_points(p):
    delta=p[..., [b for a,b in EDGES],:]-p[..., [a for a,b in EDGES],:]
    return F.normalize(delta,dim=-1,eps=1e-6)

def prepare_record(r,flip=False):
    w,h=r["size"];scale=224/max(w,h);nw,nh=round(w*scale),round(h*scale)
    left,top=(224-nw)//2,(224-nh)//2
    img=Image.open(ROOT/r["image"]).convert("RGB").resize((nw,nh),Image.Resampling.BILINEAR)
    canvas=Image.new("RGB",(224,224),(124,116,104));canvas.paste(img,(left,top))
    pm=np.array([p is not None for p in r["points"]]);p=np.array([v if v is not None else [0,0] for v in r["points"]],dtype=np.float32)
    delta=np.array([p[b]-p[a] for a,b in EDGES]);length=np.linalg.norm(delta,axis=-1)
    dm=np.array([pm[a] and pm[b] for a,b in EDGES])&(length>1e-6)
    vec=delta/np.maximum(length[:,None],1e-6);vec[~dm]=0
    p=(p*scale+np.array([left,top],dtype=np.float32))/224
    if flip:
        canvas=canvas.transpose(Image.Transpose.FLIP_LEFT_RIGHT);p[:,0]=1-p[:,0];vec[:,0]*=-1
    p[~pm]=0
    image=torch.from_numpy(np.asarray(canvas).copy()).permute(2,0,1).float()/255
    image=(image-torch.tensor([.485,.456,.406])[:,None,None])/torch.tensor([.229,.224,.225])[:,None,None]
    return image,p,pm,vec,dm

def build_features(dataset):
    from torchvision.models import resnet18,ResNet18_Weights
    signature=hashlib.sha256(json.dumps(dataset,sort_keys=True).encode()).hexdigest()
    cache=OUT/"features.pt"
    if cache.exists():
        saved=torch.load(cache,weights_only=False)
        if saved["signature"]==signature:return saved
    base=resnet18(weights=ResNet18_Weights.DEFAULT).eval()
    encoder=nn.Sequential(*list(base.children())[:-2],nn.AdaptiveAvgPool2d((2,2)),nn.Flatten()).eval()
    samples=[];images=[]
    for r in dataset["records"]:
        for flip in ([False,True] if r["split"]=="train" else [False]):
            image,p,pm,v,dm=prepare_record(r,flip);images.append(image)
            samples.append(dict(frame_id=r["frame_id"],split=r["split"],source=r["source"],weight=r["weight"],flip=flip,p=p,pm=pm,v=v,dm=dm))
    feats=[]
    with torch.inference_mode():
        for i in range(0,len(images),12):
            feats.append(encoder(torch.stack(images[i:i+12])).clone())
            print(f"features {min(i+12,len(images))}/{len(images)}",flush=True)
    x=torch.cat(feats);saved=dict(signature=signature,x=x,samples=samples)
    torch.save(saved,cache)
    return saved

def tensors(samples):
    return {k:torch.tensor(np.stack([s[k] for s in samples]),dtype=torch.float32) for k in ["p","pm","v","dm","weight"]}

class Head(nn.Module):
    def __init__(self,dim,arm):
        super().__init__();self.arm=arm
        self.shared=nn.Sequential(nn.Linear(dim,128),nn.ReLU(),nn.Dropout(.1))
        self.geometry=nn.Linear(128,28 if arm=="direct" else 42)
        self.visible=nn.Linear(128,14)
    def forward(self,x):
        h=self.shared(x);g=self.geometry(h)
        if self.arm=="direct":p=None;v=F.normalize(g.reshape(-1,14,2),dim=-1,eps=1e-6)
        else:p=g.reshape(-1,21,2);v=directions_from_points(p)
        return p,v,self.visible(h)

def objective(output,t,arm):
    p,v,logits=output
    target_v=t["v"][:,D_PERM];dm=t["dm"][:,D_PERM]
    angular=((1-(v[:,None]*target_v).sum(-1))*dm).sum(-1)/dm.sum(-1).clamp_min(1)
    visibility=F.binary_cross_entropy_with_logits(logits[:,None].expand_as(dm),dm,reduction="none").mean(-1)
    if p is not None:
        pm=t["pm"][:,P_PERM];target_p=t["p"][:,P_PERM]
        coordinate=((p[:,None]-target_p).square().sum(-1)*pm).sum(-1)/pm.sum(-1).clamp_min(1)
        geom=coordinate*4 if arm=="keypoint" else coordinate*4+angular
    else:geom=angular
    best=(geom+.05*visibility).min(dim=1).values
    return (best*t["weight"]).sum()/t["weight"].sum()

def align_metrics(v,logits,t):
    """Ground-truth mask scores all available directions, no confidence gating.
    Choose only whole-leg swaps; never mix segments of different predicted legs.
    """
    target=t["v"][:,D_PERM];mask=t["dm"][:,D_PERM]
    dot=(v[:,None]*target).sum(-1).clamp(-1,1)
    angle=torch.acos(dot)*180/math.pi
    zero=(torch.linalg.vector_norm(v,dim=-1)<1e-5)[:,None]
    angle=torch.where(zero,torch.full_like(angle,180),angle)
    means=(angle*mask).sum(-1)/mask.sum(-1).clamp_min(1)
    choice=means.argmin(dim=1);idx=torch.arange(len(v))
    a=angle[idx,choice];m=mask[idx,choice]
    image_mae=(a*m).sum(-1)/m.sum(-1).clamp_min(1)
    # Availability is descriptive only; never used to hide an angle error.
    usable=logits.sigmoid()>=.5
    tp=(usable*m.bool()).sum().item();fp=(usable*~m.bool()).sum().item();fn=((~usable)*m.bool()).sum().item()
    groups={"head":[0],"neck":[1],"body":[2],"tail":[3],"front":[4,5,6,7],"back":[8,9,10,11,12,13]}
    return dict(mae_deg=image_mae.mean().item(),micro_mae_deg=(a*m).sum().item()/max(m.sum().item(),1),within15=((a<=15)*m).sum().item()/max(m.sum().item(),1),within30=((a<=30)*m).sum().item()/max(m.sum().item(),1),availability_precision=tp/max(tp+fp,1),availability_recall=tp/max(tp+fn,1),components={k:(a[:,ix]*m[:,ix]).sum().item()/max(m[:,ix].sum().item(),1) for k,ix in groups.items()},per_image=image_mae.tolist(),angles=a.tolist(),mask=m.tolist(),matched_permutation=choice.tolist())

def train_one(x,targets,train_idx,val_idx,test_idx,samples,arm,seed,regime):
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    net=Head(x.shape[1],arm);opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.001)
    best=math.inf;state=None;best_epoch=0;trace=[]
    def select(ix):return{k:v[ix] for k,v in targets.items()}
    tr,va,te=select(train_idx),select(val_idx),select(test_idx)
    start=time.time()
    for epoch in range(1,301):
        net.train();opt.zero_grad();loss=objective(net(x[train_idx]),tr,arm);loss.backward();opt.step()
        if epoch%5==0:
            net.eval()
            with torch.no_grad():
                _,v,z=net(x[val_idx]);score=align_metrics(v,z,va)["mae_deg"]
            trace.append([epoch,loss.item(),score])
            if score<best:best=score;state=copy.deepcopy(net.state_dict());best_epoch=epoch
    net.load_state_dict(state);net.eval()
    with torch.no_grad():
        _,v,z=net(x[test_idx]);metrics=align_metrics(v,z,te)
    elapsed=time.time()-start
    folder=OUT/"runs"/f"{regime}_{arm}_s{seed}";folder.mkdir(parents=True,exist_ok=True)
    torch.save(dict(state_dict=state,arm=arm,input_dim=x.shape[1],seed=seed,regime=regime,direction_names=NAMES,preprocessing="224 square letterbox; ImageNet normalization; frozen resnet18 spatial2x2; see direction_pilot.py",feature_scale_file="feature_scale.pt"),folder/"head.pt")
    result=dict(arm=arm,seed=seed,regime=regime,train_count=len(train_idx)//2,val_count=len(val_idx),test_count=len(test_idx),best_epoch=best_epoch,val_mae_deg=best,seconds=elapsed,metrics=metrics,test_frame_ids=[samples[i]["frame_id"] for i in test_idx],test_vectors=v.tolist(),test_availability=z.sigmoid().tolist(),trace=trace)
    write(folder/"result.json",result)
    print(json.dumps({k:result[k] for k in ["regime","arm","seed","best_epoch","val_mae_deg","seconds"]})+f" test_mae={metrics['mae_deg']:.2f}",flush=True)
    return result

def summarize(results):
    rows=[]
    for regime in ["human_only","human_plus_agent"]:
        for arm in ["keypoint","keypoint_angle","direct"]:
            rr=[r for r in results if r["regime"]==regime and r["arm"]==arm]
            rows.append(dict(regime=regime,arm=arm,train_images=rr[0]["train_count"],mean_mae_deg=float(np.mean([r["metrics"]["mae_deg"] for r in rr])),seed_sd=float(np.std([r["metrics"]["mae_deg"] for r in rr])),within15=float(np.mean([r["metrics"]["within15"] for r in rr])),within30=float(np.mean([r["metrics"]["within30"] for r in rr])),components={k:float(np.mean([r["metrics"]["components"][k] for r in rr])) for k in rr[0]["metrics"]["components"]}))
    comparisons=[]
    for regime in ["human_only","human_plus_agent"]:
        for baseline in ["keypoint","keypoint_angle"]:
            paired=[]
            for seed in [11,29,47]:
                a=next(r for r in results if r["regime"]==regime and r["arm"]==baseline and r["seed"]==seed)
                b=next(r for r in results if r["regime"]==regime and r["arm"]=="direct" and r["seed"]==seed)
                paired.append(np.array(a["metrics"]["per_image"])-np.array(b["metrics"]["per_image"]))
            delta=np.mean(paired,axis=0)
            # Correlated nearby frames count as one scene group for uncertainty.
            ids=a["test_frame_ids"];groups=[]
            for i,fid in enumerate(ids):
                t=int(fid[8:14])
                if groups and t-int(ids[groups[-1][-1]][8:14])<=12:groups[-1].append(i)
                else:groups.append([i])
            rng=np.random.default_rng(7001);boot=[]
            for _ in range(5000):
                sampled=rng.integers(0,len(groups),len(groups));ix=[i for g in sampled for i in groups[g]];boot.append(delta[ix].mean())
            comparisons.append(dict(regime=regime,baseline=baseline,positive_means_direct_better_deg=float(delta.mean()),bootstrap_scene_ci95=np.quantile(boot,[.025,.975]).tolist(),test_scene_groups=len(groups),per_image_delta=delta.tolist()))
    return dict(rows=rows,paired_comparisons=comparisons,interpretation="frozen-feature exploratory comparison only; not a replacement for independently retraining and evaluating YOLO-Pose",test_labels="12 human-authored frames in episode24; no agent labels in evaluation",source_integrity="checked before and after")

def overlays(dataset):
    frames=[r for r in dataset["records"] if r["source"]=="agent_new_visual"]
    colors=[(0,125,245),(15,174,210),(227,177,0),(227,177,0),(15,210,90),(15,210,90),(240,127,10),(240,127,10)]+[(233,32,183)]*3+[(20,190,216)]*3
    for page in range(4):
        canvas=Image.new("RGB",(1280,1040),(250,250,250));d=ImageDraw.Draw(canvas)
        for j,r in enumerate(frames[page*4:page*4+4]):
            im=Image.open(ROOT/r["image"]).convert("RGB");scale=min(610/im.width,470/im.height);im=im.resize((round(im.width*scale),round(im.height*scale)))
            x=(j%2)*640+(640-im.width)//2;y=(j//2)*520+35;canvas.paste(im,(x,y));d.text(((j%2)*640+12,(j//2)*520+10),r["frame_id"],fill="black")
            for i,(a,b) in enumerate(EDGES):
                p,q=r["points"][a],r["points"][b]
                if p is None or q is None:continue
                start=(x+p[0]*scale,y+p[1]*scale);end=(x+q[0]*scale,y+q[1]*scale);d.line([start,end],fill=colors[i],width=3)
                vx,vy=end[0]-start[0],end[1]-start[1];n=max(math.hypot(vx,vy),1);ux,uy=vx/n,vy/n
                d.polygon([end,(end[0]-8*ux+4*uy,end[1]-8*uy-4*ux),(end[0]-8*ux-4*uy,end[1]-8*uy+4*ux)],fill=colors[i])
        canvas.save(OUT/f"new-annotation-check-{page+1}.jpg",quality=93)

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--overlays-only",action="store_true");args=parser.parse_args()
    if not args.overlays_only and any((OUT/"runs").glob("*/result.json")):
        raise RuntimeError("Refusing to overwrite this completed experiment; use a new experiment directory")
    dataset=read(OUT/"dataset.json")
    for path,fingerprint in dataset["source_hashes"].items():assert sha(ROOT/path)==fingerprint,path
    overlays(dataset)
    if args.overlays_only:return
    features=build_features(dataset);samples=features["samples"];x=features["x"].clone()
    train_all=[i for i,s in enumerate(samples) if s["split"]=="train"]
    train_human=[i for i in train_all if samples[i]["source"]=="human_official"]
    # Same scaler for both regimes, fit exclusively to human training images.
    mean=x[train_human].mean(0);std=x[train_human].std(0).clamp_min(.1);x=(x-mean)/std
    torch.save(dict(mean=mean,std=std),OUT/"feature_scale.pt")
    t=tensors(samples);val_idx=[i for i,s in enumerate(samples) if s["split"]=="val"];test_idx=[i for i,s in enumerate(samples) if s["split"]=="test"]
    results=[]
    for regime,train_idx in [("human_only",train_human),("human_plus_agent",train_all)]:
        for seed in [11,29,47]:
            for arm in ["keypoint","keypoint_angle","direct"]:
                result_path=OUT/"runs"/f"{regime}_{arm}_s{seed}"/"result.json"
                if result_path.exists():raise RuntimeError(f"Refusing to overwrite existing experiment: {result_path}")
                results.append(train_one(x,t,train_idx,val_idx,test_idx,samples,arm,seed,regime))
    for path,fingerprint in dataset["source_hashes"].items():assert sha(ROOT/path)==fingerprint,path
    summary=summarize(results);summary["environment"]=dict(torch=torch.__version__,device="cpu",encoder_weights_sha256=sha(OUT/"weights/hub/checkpoints/resnet18-f37072fd.pth"),dataset_sha256=sha(OUT/"dataset.json"),protocol_sha256=sha(OUT/"protocol.json"))
    write(OUT/"summary.json",summary);print(json.dumps(summary["rows"],ensure_ascii=False),flush=True)

if __name__=="__main__":main()
