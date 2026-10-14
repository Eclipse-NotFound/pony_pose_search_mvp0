"""End-to-end image-to-keypoint versus image-to-direction experiment.

Only experiment files are written. Evaluation labels never select settings.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import copy
import gc
import math
import random
import time
import numpy as np
from PIL import Image
import torch
from torch import nn
from torch.nn import functional as F
from torchvision.models import resnet18
from direction_expanded_data import ROOT, OUT, OLD, EDGES, NAMES, read, write, sha
from direction_pilot import P_PERM, D_PERM, align_metrics, directions_from_points

SIZE = 224
WEIGHTS = OLD/'weights/hub/checkpoints/resnet18-f37072fd.pth'


def prepare(r):
    w, h = r['size']; scale = SIZE/max(w,h)
    nw, nh = round(w*scale), round(h*scale); left, top = (SIZE-nw)//2, (SIZE-nh)//2
    with Image.open(ROOT/r['image']) as im:
        im = im.convert('RGB').resize((nw,nh), Image.Resampling.BILINEAR)
        canvas = Image.new('RGB', (SIZE,SIZE), (124,116,104)); canvas.paste(im, (left,top))
    pm = np.array([p is not None for p in r['points']])
    p = np.array([p if p is not None else [0,0] for p in r['points']], dtype=np.float32)
    # Pixel centers in continuous letterbox coordinates; consistent with flipping.
    p = ((p+.5)*scale+np.array([left,top]))/SIZE; p[~pm] = 0
    delta = p[[b for a,b in EDGES]]-p[[a for a,b in EDGES]]
    length = np.linalg.norm(delta, axis=-1)
    dm = np.array([pm[a] and pm[b] for a,b in EDGES]) & (length>1e-6)
    v = delta/np.maximum(length[:,None],1e-6); v[~dm] = 0
    image = torch.from_numpy(np.asarray(canvas).copy()).permute(2,0,1).float()/255
    return image, dict(p=p, pm=pm, v=v, dm=dm, weight=r['weight'])


def tensor_data(records, device):
    rows = [prepare(r) for r in records]
    x = torch.stack([r[0] for r in rows]).to(device)
    t = {k:torch.tensor(np.stack([r[1][k] for r in rows]),dtype=torch.float32,device=device)
         for k in ['p','pm','v','dm','weight']}
    return x,t


def normalize_image(x):
    mean = x.new_tensor([.485,.456,.406])[None,:,None,None]
    std = x.new_tensor([.229,.224,.225])[None,:,None,None]
    return (x-mean)/std


def augment(x,t,rng):
    x=x.clone();t={k:v.clone() for k,v in t.items()}
    flip=torch.tensor(rng.random(len(x))<.5,device=x.device)
    x[flip]=x[flip].flip(-1)
    t['p'][flip,:,0]=1-t['p'][flip,:,0]
    t['p']*=t['pm'][...,None];t['v'][flip,:,0]*=-1
    brightness=torch.tensor(rng.uniform(.85,1.15,len(x)),device=x.device,dtype=x.dtype)
    return (x*brightness[:,None,None,None]).clamp(0,1),t


def gaussian_maps(p, size=28, sigma=1.25):
    grid=(torch.arange(size,device=p.device,dtype=p.dtype)+.5)/size
    yy,xx=torch.meshgrid(grid,grid,indexing='ij')
    d=((xx-p[...,0,None,None]).square()+(yy-p[...,1,None,None]).square())
    return (-d/(2*(sigma/size)**2)).flatten(-2).softmax(-1)


def points_from_maps(logits):
    h,w=logits.shape[-2:];prob=logits.flatten(-2).softmax(-1).reshape_as(logits)
    xx=(torch.arange(w,device=logits.device,dtype=logits.dtype)+.5)/w
    yy=(torch.arange(h,device=logits.device,dtype=logits.dtype)+.5)/h
    return torch.stack([(prob.sum(-2)*xx).sum(-1),(prob.sum(-1)*yy).sum(-1)],-1)


class PoseNet(nn.Module):
    def __init__(self,arm,pretrained=True):
        super().__init__();self.arm=arm
        base=resnet18(weights=None)
        if pretrained:
            base.load_state_dict(torch.load(WEIGHTS,map_location='cpu',weights_only=True))
        self.encoder=nn.Sequential(*list(base.children())[:-2])
        self.pool=nn.Sequential(nn.AdaptiveAvgPool2d((2,2)),nn.Flatten())
        self.availability=nn.Sequential(nn.Linear(2048,128),nn.ReLU(),nn.Linear(128,14))
        if arm=='keypoint_heatmap':
            self.geometry=nn.Sequential(nn.Conv2d(512,128,3,padding=1),nn.ReLU(),
                nn.Upsample(scale_factor=2,mode='bilinear',align_corners=False),
                nn.Conv2d(128,64,3,padding=1),nn.ReLU(),
                nn.Upsample(scale_factor=2,mode='bilinear',align_corners=False),nn.Conv2d(64,21,1))
        elif arm=='direct_vector':
            self.geometry=nn.Sequential(nn.Linear(2048,128),nn.ReLU(),nn.Dropout(.1),nn.Linear(128,28))
        else:
            raise ValueError(arm)
    def train(self,mode=True):
        super().train(mode)
        for m in self.encoder.modules():
            if isinstance(m,nn.BatchNorm2d):m.eval()
        return self
    def forward(self,x):
        f=self.encoder(x);pooled=self.pool(f);z=self.availability(pooled)
        if self.arm=='keypoint_heatmap':
            hm=self.geometry(f);p=points_from_maps(hm);v=directions_from_points(p)
        else:
            hm=None;p=None;v=F.normalize(self.geometry(pooled).reshape(-1,14,2),dim=-1,eps=1e-6)
        return dict(p=p,v=v,z=z,hm=hm)


def objective(out,t,arm):
    pp=torch.as_tensor(P_PERM,device=out['v'].device);dp=torch.as_tensor(D_PERM,device=out['v'].device)
    dm=t['dm'][:,dp]
    visibility=F.binary_cross_entropy_with_logits(out['z'][:,None].expand_as(dm),dm,reduction='none').mean(-1)
    if arm=='keypoint_heatmap':
        pm=t['pm'][:,pp];target_p=t['p'][:,pp]
        hm=gaussian_maps(t['p'])[:,pp]
        ce=-(out['hm'].flatten(-2).log_softmax(-1)[:,None]*hm).sum(-1)
        coord=(out['p'][:,None]-target_p).square().sum(-1)
        geom=((ce+4*coord)*pm).sum(-1)/pm.sum(-1).clamp_min(1)
    else:
        angle=1-(out['v'][:,None]*t['v'][:,dp]).sum(-1)
        geom=(angle*dm).sum(-1)/dm.sum(-1).clamp_min(1)
    per_image=(geom+.1*visibility).min(-1).values
    return (per_image*t['weight']).sum()/t['weight'].sum()


def metric(out,t):
    out={k:None if v is None else v.detach().cpu() for k,v in out.items()}
    t={k:v.detach().cpu() for k,v in t.items()}
    m=align_metrics(out['v'],out['z'],t)
    valid=t['dm'].sum(-1)>0
    m['angular_image_count']=int(valid.sum())
    m['mae_deg']=float(np.mean(np.array(m['per_image'])[valid.numpy()])) if valid.any() else None
    m['per_image']=[v if ok else None for v,ok in zip(m['per_image'],valid.tolist())]
    if out['p'] is not None:
        pm=t['pm'][:,P_PERM]
        distance=torch.linalg.vector_norm(out['p'][:,None]-t['p'][:,P_PERM],dim=-1)
        best=((distance*pm).sum(-1)/pm.sum(-1).clamp_min(1)).argmin(-1)
        d=distance[torch.arange(len(best)),best];mask=pm[torch.arange(len(best)),best]
        m['keypoint_pck05']=float(((d<=.05)*mask).sum()/mask.sum().clamp_min(1))
        m['keypoint_mean_distance_fraction']=float((d*mask).sum()/mask.sum().clamp_min(1))
    return m


def evaluate(net,x,t,idx,records):
    outputs=[]
    net.eval()
    with torch.inference_mode():
        for start in range(0,len(idx),12):
            outputs.append(net(normalize_image(x[idx[start:start+12]])))
    out={k:None if outputs[0][k] is None else torch.cat([o[k] for o in outputs]) for k in outputs[0]}
    gt={k:v[idx] for k,v in t.items()}
    result=dict(metrics=metric(out,gt),frame_ids=[records[i]['frame_id'] for i in idx],
                vectors=out['v'].cpu().tolist(),availability=out['z'].sigmoid().cpu().tolist(),
                points_letterbox=None if out['p'] is None else out['p'].cpu().tolist())
    return result


def train_one(x,t,records,arm,regime,seed,device,epochs=80):
    folder=OUT/'runs'/f'{regime}_{arm}_s{seed}'
    if (folder/'result.json').exists():
        print('Already complete: '+folder.name,flush=True)
        return read(folder/'result.json')
    if (folder/'checkpoint.pt').exists():
        raise RuntimeError('Incomplete saved run needs explicit recovery, not overwrite: '+str(folder))
    random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    if device=='cuda':torch.cuda.manual_seed_all(seed)
    rng=np.random.default_rng(seed+100000)
    train_idx=[i for i,r in enumerate(records) if regime in r['regimes']]
    val_idx=[i for i,r in enumerate(records) if r['split']=='val']
    net=PoseNet(arm).to(device)
    encoder_params=list(net.encoder.parameters());head_params=[p for name,p in net.named_parameters() if not name.startswith('encoder.')]
    opt=torch.optim.AdamW([{'params':encoder_params,'lr':.0001},{'params':head_params,'lr':.001}],weight_decay=.001)
    schedule=torch.optim.lr_scheduler.CosineAnnealingLR(opt,T_max=epochs,eta_min=.000005)
    best=math.inf;state=None;best_epoch=None;trace=[];start=time.perf_counter()
    for epoch in range(1,epochs+1):
        net.train();order=rng.permutation(train_idx);total=0
        for begin in range(0,len(order),12):
            ids=order[begin:begin+12].tolist()
            xb,tb=augment(x[ids],{k:v[ids] for k,v in t.items()},rng)
            opt.zero_grad(set_to_none=True);loss=objective(net(normalize_image(xb)),tb,arm)
            if not torch.isfinite(loss):raise RuntimeError('Non-finite loss')
            loss.backward();nn.utils.clip_grad_norm_(net.parameters(),5);opt.step();total+=loss.item()*len(ids)
        schedule.step()
        if epoch%5==0:
            validation=evaluate(net,x,t,val_idx,records);score=validation['metrics']['mae_deg']
            trace.append(dict(epoch=epoch,loss=total/len(order),val_mae_deg=score))
            if score<best:
                best=score;best_epoch=epoch;state={k:v.detach().cpu().clone() for k,v in net.state_dict().items()}
            if epoch%10==0:print(f'{regime} {arm} s{seed} {epoch}/{epochs} val={score:.2f} best={best:.2f}',flush=True)
    net.load_state_dict(state);net.eval()
    result=dict(arm=arm,regime=regime,seed=seed,train_images=len(train_idx),best_epoch=best_epoch,
                val_mae_deg=best,seconds=time.perf_counter()-start,trace=trace,evaluations={})
    # First test inference occurs only after validation has selected the checkpoint.
    for split in ['test','challenge_agent_reference']:
        idx=[i for i,r in enumerate(records) if r['split']==split]
        result['evaluations'][split]=evaluate(net,x,t,idx,records)
    folder.mkdir(parents=True,exist_ok=True)
    torch.save(dict(state_dict=state,arm=arm,regime=regime,seed=seed,image_size=SIZE,
                    dataset_sha256=sha(OUT/'dataset.json'),protocol_sha256=sha(OUT/'protocol.json')),folder/'checkpoint.pt')
    write(folder/'result.json',result)
    print(f"DONE {folder.name} human={result['evaluations']['test']['metrics']['mae_deg']:.2f} challenge={result['evaluations']['challenge_agent_reference']['metrics']['mae_deg']:.2f}",flush=True)
    del net,opt,state;gc.collect()
    if device=='cuda':torch.cuda.empty_cache()
    return result


def summarize(results):
    rows=[]
    for split in ['test','challenge_agent_reference']:
        for regime in ['base55','expanded103']:
            for arm in ['keypoint_heatmap','direct_vector']:
                rr=[r for r in results if r['arm']==arm and r['regime']==regime]
                if not rr:continue
                mm=[r['evaluations'][split]['metrics'] for r in rr]
                keys=['mae_deg','micro_mae_deg','within15','within30','availability_precision','availability_recall']
                row=dict(split=split,regime=regime,arm=arm,seeds=[r['seed'] for r in rr],train_images=rr[0]['train_images'],
                         **{k:float(np.mean([m[k] for m in mm])) for k in keys})
                row['seed_sd']=float(np.std([m['mae_deg'] for m in mm]))
                row['components']={k:float(np.mean([m['components'][k] for m in mm])) for k in mm[0]['components']}
                if arm=='keypoint_heatmap':row['keypoint_pck05']=float(np.mean([m['keypoint_pck05'] for m in mm]))
                rows.append(row)
    return dict(rows=rows,selection='validation only; three seeds reported, not best test seed',
                evaluation_note=read(OUT/'dataset.json')['evaluation_note'],
                dataset_sha256=sha(OUT/'dataset.json'),protocol_sha256=sha(OUT/'protocol.json'),
                encoder_weights_sha256=sha(WEIGHTS),torch=torch.__version__,cuda=torch.version.cuda,
                gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--device',default='cuda',choices=['cpu','cuda'])
    parser.add_argument('--regime',choices=['base55','expanded103']);parser.add_argument('--arm',choices=['keypoint_heatmap','direct_vector'])
    parser.add_argument('--seed',type=int,choices=[11,29,47]);args=parser.parse_args()
    torch.set_num_threads(4);torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    if args.device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA is unavailable')
    data=read(OUT/'dataset.json');protocol=read(OUT/'protocol.json')
    for path,h in data['source_hashes'].items():assert sha(ROOT/path)==h,path
    x,t=tensor_data(data['records'],args.device)
    for regime in ([args.regime] if args.regime else protocol['regimes']):
        for seed in ([args.seed] if args.seed else protocol['seeds']):
            for arm in ([args.arm] if args.arm else protocol['arms']):
                train_one(x,t,data['records'],arm,regime,seed,args.device,protocol['epochs'])
    for path,h in data['source_hashes'].items():assert sha(ROOT/path)==h,path
    results=[read(p) for p in sorted((OUT/'runs').glob('*/result.json'))]
    write(OUT/'summary.json',summarize(results))


if __name__=='__main__':main()
