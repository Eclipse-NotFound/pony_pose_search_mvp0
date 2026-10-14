"""Model subprocess: consumes only frozen packages/inputs, writes job-local output."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts/common'),str(ROOT/'scripts/ai')]
from multispecies.catalog import require
from multispecies.library import _atomic_json
from multispecies.keypoints import ORDER, PROFILES
from multispecies.importers import LEGACY_MAPPING


def check_image(item):
    path=Path(item['path'])
    require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],'模型输入图片已变化')


def predict(request):
    from PIL import Image
    spec=request['model']
    require(hashlib.sha256(Path(spec['path']).read_bytes()).hexdigest()==spec['model_sha256'],'模型内容已变化')
    result=[]
    if spec['backend']=='body14_resnet':
        import torch
        from direction_expanded_train import PoseNet, normalize_image
        saved=torch.load(spec['path'],map_location='cpu',weights_only=True)
        require(saved.get('arm')=='direct_vector','此权重不是直接方向模型')
        model=PoseNet('direct_vector',pretrained=False);model.load_state_dict(saved['state_dict']);model.eval()
    else:
        from ultralytics import YOLO
        model=YOLO(spec['path'])
    for item in request['inputs']:
        check_image(item)
        with Image.open(item['path']) as im:
            image=im.convert('RGB');w,h=image.size
        if spec['backend']=='body14_resnet':
            import torch
            tensor=letterbox(image,saved.get('image_size',224))
            with torch.inference_mode():out=model(normalize_image(tensor[None]))
            values=out['v'][0].tolist();availability=out['z'][0].sigmoid().tolist()
            active=item['record']['annotation']['directions']
            changes={'directions':{k:{'value':v if score>=.5 else None,'visibility':'unknown',
                'missing_reason':None if score>=.5 else 'not_discernible'} for k,v,score in zip(spec['directions'],values,availability) if k in active}}
            require(changes['directions'],'请先在标注中确认角色部位存在')
            result.append({'id':item['id'],'changes':changes})
        else:
            predictions=model.predict(image,verbose=False,device='cpu')
            if spec['backend']=='yolo_detection':
                boxes=[]
                for p in predictions:
                    if p.boxes is None:continue
                    for box,score,cls in zip(p.boxes.xyxy.tolist(),p.boxes.conf.tolist(),p.boxes.cls.tolist()):
                        form=spec['forms'].get(str(int(cls)))
                        if form is None:continue
                        x1,y1,x2,y2=box;x1=max(0,math.floor(x1));y1=max(0,math.floor(y1));x2=min(w,math.ceil(x2));y2=min(h,math.ceil(y2))
                        if x2>x1 and y2>y1:boxes.append({'roi':[x1,y1,x2-x1,y2-y1],'form_ref':form,'confidence':score})
                result.append({'id':item['id'],'boxes':boxes})
            else:
                require(spec['point_order']==ORDER,'点位语义顺序不一致')
                points=None
                for p in predictions:
                    if p.keypoints is not None and len(p.keypoints)>0:
                        # A crop represents one occurrence; reject ambiguous multi-person output.
                        require(len(p.keypoints)==1,'裁剪图检测出多个角色，请先核对角色框')
                        points=p.keypoints.data[0].tolist();break
                require(points is not None and len(points)==len(ORDER),'未得到匹配 schema 的点位预测')
                values={}
                for key,point in zip(ORDER,points):
                    known=len(point)>=3 and point[2]>=.25
                    values[key]={'value':[min(w,max(0,point[0])),min(h,max(0,point[1]))] if known else None,
                                 'visibility':'unknown','missing_reason':None if known else 'not_discernible'}
                result.append({'id':item['id'],'changes':{'keypoints':{'points':values}}})
    return {'predictions':result}


def letterbox(image, size):
    import numpy as np
    import torch
    from PIL import Image
    w,h=image.size;scale=size/max(w,h);nw,nh=round(w*scale),round(h*scale)
    canvas=Image.new('RGB',(size,size),(124,116,104))
    canvas.paste(image.resize((nw,nh),Image.Resampling.BILINEAR),((size-nw)//2,(size-nh)//2))
    return torch.from_numpy(np.asarray(canvas).copy()).permute(2,0,1).float()/255


def train_direction(request):
    import numpy as np
    import torch
    from PIL import Image
    from direction_expanded_train import PoseNet, normalize_image, objective
    from multispecies.keypoints import PROFILES
    package=request['package'];order=list(LEGACY_MAPPING.values())
    entries=package['records']
    require(all(e['profile_ref'] in PROFILES for e in entries),'现有方向训练器只支持小马 body14；其他身体需登记对应训练器')
    torch.manual_seed(request['seed']);torch.set_num_threads(4)
    device_name=str(request['device']);device=torch.device('cuda:'+device_name if device_name.isdigit() else device_name)
    model=PoseNet('direct_vector',pretrained=False).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0003)
    train=[e for e in entries if e['split']=='train'];validation=[e for e in entries if e['split']=='validation']
    def batch(rows):
        images=[];values=[];masks=[]
        for e in rows:
            with Image.open(e['image_path']) as im:images.append(letterbox(im.convert('RGB'),request['image_size']))
            indices=[e['channel_order'].index(k) for k in order]
            values.append([e['values'][i] or [0,0] for i in indices]);masks.append([e['mask'][i] for i in indices])
        require(any(any(x) for x in masks),'没有 body14 可训练方向')
        return torch.stack(images).to(device),{'v':torch.tensor(values,dtype=torch.float32,device=device),
            'dm':torch.tensor(masks,dtype=torch.float32,device=device),'weight':torch.ones(len(rows),device=device)}
    best=float('inf');history=[];out=Path(request['output_dir']);rng=np.random.default_rng(request['seed'])
    for epoch in range(request['epochs']):
        model.train();losses=[]
        for indices in np.array_split(rng.permutation(len(train)),max(1,math.ceil(len(train)/request['batch']))):
            x,t=batch([train[i] for i in indices]);optimizer.zero_grad();loss=objective(model(normalize_image(x)),t,'direct_vector')
            loss.backward();optimizer.step();losses.append(float(loss.detach()))
        model.eval();values=[]
        with torch.inference_mode():
            for start in range(0,len(validation),request['batch']):
                x,t=batch(validation[start:start+request['batch']]);values.append(float(objective(model(normalize_image(x)),t,'direct_vector')))
        score=sum(values)/len(values);history.append({'epoch':epoch+1,'train_loss':sum(losses)/len(losses),'validation_loss':score})
        print(json.dumps(history[-1]),flush=True)
        _atomic_json(out/'progress.json',{'epoch':epoch+1,'epochs':request['epochs'],'validation_loss':score})
        if score<best:
            best=score;torch.save({'arm':'direct_vector','state_dict':model.cpu().state_dict(),'snapshot_sha256':package['snapshot_sha256'],
                                 'directions':order,'image_size':request['image_size']},out/'best.pt');model.to(device)
    return {'model_path':str(out/'best.pt'),'backend':'body14_resnet','profiles':sorted(PROFILES),'directions':order,
            'history':history,'snapshot_sha256':package['snapshot_sha256'],'initialization':'random_resnet18','test_set_used':False}


def train_yolo(request):
    from ultralytics import YOLO
    import ultralytics
    import re
    package=request['package'];out=Path(request['output_dir'])
    if package['task']=='keypoints':
        base=Path(ultralytics.__file__).parent/'cfg/models/v8/yolov8-pose.yaml'
        text=re.sub(r'kpt_shape: \[[0-9]+, [0-9]+\]',f'kpt_shape: [{len(ORDER)}, 3]',base.read_text(encoding='utf-8'))
        config=out/'yolov8n-pose-custom.yaml';config.write_text(text,encoding='utf-8')
        model=YOLO(str(config));backend='yolo_pose'
    else:
        model=YOLO('yolov8n.yaml');backend='yolo_detection'
    model.train(data=package['data_yaml'],epochs=request['epochs'],imgsz=request['image_size'],batch=request['batch'],
                device=request['device'],workers=0,seed=request['seed'],project=str(out),name='training',exist_ok=True,
                pretrained=False,amp=False,plots=False,verbose=False)
    model_path=out/'training/weights/best.pt'
    require(model_path.is_file(),'训练没有生成 best.pt')
    result={'model_path':str(model_path),'backend':backend,'snapshot_sha256':package['snapshot_sha256'],'test_set_used':False}
    if backend=='yolo_pose':result.update(point_order=ORDER,profiles=sorted(PROFILES))
    else:
        classes=sorted({r['form_ref'] for e in package['records'] for r in e['regions']})
        result['forms']={str(i):name for i,name in enumerate(classes)}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',type=Path,required=True)
    args=parser.parse_args();request=json.loads(args.request.read_text(encoding='utf-8'))
    # Every cache/write produced by optional ML packages belongs to this job.
    out=Path(request['output_dir']);out.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('YOLO_CONFIG_DIR',str(out/'yolo_config'))
    os.environ.setdefault('MPLCONFIGDIR',str(out/'mpl_config'))
    os.environ['YOLO_AUTOINSTALL']='false'
    if request['operation']=='predict':result=predict(request)
    else:
        from workflow.training import TrainingWorkflow
        TrainingWorkflow.verify_package(request['package'])
        result=train_direction(request) if request['package']['task']=='directions' else train_yolo(request)
    _atomic_json(out/'result.json',result)


if __name__=='__main__':main()
