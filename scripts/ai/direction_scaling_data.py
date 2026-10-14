"""Selection, manually inspected labels and immutable learning-curve datasets."""
import sys
sys.dont_write_bytecode=True
import argparse,copy,math,random
from collections import Counter,defaultdict
from PIL import Image,ImageDraw
from direction_pilot_data import ROOT,EDGES,NAMES,read,write,sha
from direction_scaling_select import OUT,PREVIOUS

EXISTING=[20,24,36,43,52,56,57,62,65,70,73,76,79,92,117,120,131,141,148,153,157,160,163,166,171,175,177,192,203,207,211,218,471,852,855,1039,1078,1082,1126,1208]
FULL=[412,416,420,424,425,431,433,434,438,439,445,447,461,475,501,510,512,513,514,521,526,528,529,534,539,544,557,
568,571,594,601,603,621,622,623,638,640,643,652,653,654,659,661,663,684,686,689,690,691,692,694,695,699,701,705,708,711,714,717,
720,724,726,731,733,734,736,737,742,745,747,751,770,771,772,775,791,800,809,815,816,830,831,833,843,844,856,857,860,861,862,865,867,870,
872,883,884,885,896,902,905,913,920,928,931,932,934,939,945,950,975,989,995,1002,1003,1008,1011,1014,1023,1031,1033,1037,1040,1042,1052,1053,1071,1089,1093,1099,1101,1103,1106,1108,1109,
1112,1122,1139,1147,1150,1162,1163,1167,1171,1184,1187,1197,1199,1210,1211,1231,1237,1239,1240,1242,1248,1258,1260,1267,1272,1274]

def fid(t):return f's01e15_t{t:06d}_f000'

def grids(rows, labels=None):
    for offset in range(0,len(rows),4):
        canvas=Image.new('RGB',(1280,1120),'#f4f4f4');d=ImageDraw.Draw(canvas)
        for j,r in enumerate(rows[offset:offset+4]):
            with Image.open(ROOT/r['image']) as im:
                im=im.convert('RGB');scale=min(560/im.width,490/im.height);im=im.resize((round(im.width*scale),round(im.height*scale)))
            x=(j%2)*640+45;y=(j//2)*560+40;w,h=im.size
            canvas.paste(im,(x,y));d.text((x,y-25),r['frame_id'],fill='black')
            if labels is None:
                for v in range(0,101,10):
                    xx=x+w*v/100;yy=y+h*v/100
                    d.line([(xx,y),(xx,y+h)],fill='#779999',width=1);d.text((xx,y-13),str(v),fill='black')
                    d.line([(x,yy),(x+w,yy)],fill='#779999',width=1);d.text((x-21,yy),str(v),fill='black')
            else:
                p=labels[r['frame_id']]['points_percent']
                colors=['#087cfa','#11abc0','#d7a600','#d7a600','#12b35a','#12b35a','#f78312','#f78312','#c618ae','#c618ae','#c618ae','#10b7c6','#10b7c6','#10b7c6']
                for k,(a,b) in enumerate(EDGES):
                    if p[a] is None or p[b] is None:continue
                    x1,y1=x+p[a][0]*w/100,y+p[a][1]*h/100;x2,y2=x+p[b][0]*w/100,y+p[b][1]*h/100
                    d.line([(x1,y1),(x2,y2)],fill=colors[k],width=3)
                    d.ellipse((x2-3,y2-3,x2+3,y2+3),fill=colors[k])
        prefix='label-grid' if labels is None else 'annotation-check'
        canvas.save(OUT/f'{prefix}-{offset//4+1:02}.jpg',quality=93)

def select():
    assert not (OUT/'runs').exists()
    allrows={r['frame_id']:r for r in read(OUT/'inventory.json')['eligible_crops']+read(OUT/'crop_proposals.json')['frames']}
    rows=[copy.deepcopy(allrows[fid(t)]) for t in sorted(EXISTING+FULL)]
    assert len(set(EXISTING+FULL))==len(rows)
    print('selection',len(rows),'existing',len(EXISTING),'new crops',len(FULL))
    previous=read(PREVIOUS/'dataset.json');seen={sha(ROOT/r['image']) for r in previous['records']}
    for r in rows:
        h=sha(ROOT/r['image']);assert h not in seen,r['frame_id'];seen.add(h)
        r['split']='train';r['selection_reason']='visually screened pose/view/occlusion diversity; no model keypoints used'
    write(OUT/'selection.json',dict(status='visually_screened_before_annotation',frames=rows))
    grids(rows)

def parse_labels():
    rows={}
    for path in sorted((OUT/'labels').glob('batch-*.txt')):
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.startswith('#'):continue
            sec,coords,note=line.split('|');points=[None if v=='-' else [float(x) for x in v.split(',')] for v in coords.split()]
            assert len(points)==21,(sec,len(points),path)
            assert all(p is None or (len(p)==2 and all(0<=v<100 for v in p)) for p in points),sec
            key=fid(int(sec));assert key not in rows,key
            rows[key]=dict(frame_id=key,points_percent=points,notes=note,source_file=path.relative_to(ROOT).as_posix())
    return rows

def build(partial=False):
    assert not (OUT/'runs').exists(),'Frozen once training starts'
    selected=read(OUT/'selection.json')['frames'];labels=parse_labels()
    print('labels',len(labels),'/',len(selected))
    if partial:
        grids([r for r in selected if r['frame_id'] in labels],labels);return
    assert set(labels)=={r['frame_id'] for r in selected}
    previous=read(PREVIOUS/'dataset.json');hashes=copy.deepcopy(previous['source_hashes'])
    for p,h in hashes.items():assert sha(ROOT/p)==h,p
    records=copy.deepcopy(previous['records'])
    for r in records:r['regimes']=['n103','n203','n303'] if r['split']=='train' else []
    # Deterministic nested subset, balanced over consecutive groups of 10 selected frames.
    rng=random.Random(20261009);mid=set()
    for start in range(0,len(selected),10):mid.update(r['frame_id'] for r in rng.sample(selected[start:start+10],5))
    assert len(selected)==200 and len(mid)==100
    for s in selected:
        l=labels[s['frame_id']]
        with Image.open(ROOT/s['image']) as im:w,h=im.size
        points=[None if p is None else [round(p[0]*w/100,3),round(p[1]*h/100,3)] for p in l['points_percent']]
        r=dict(frame_id=s['frame_id'],image=s['image'],size=[w,h],points=points,split='train',source='agent_scaling_visual_20261009',weight=.5,
               regimes=['n203','n303'] if s['frame_id'] in mid else ['n303'],notes=l['notes'],review_status='unreviewed_experimental_only')
        r['directions']={}
        for name,(a,b) in zip(NAMES,EDGES):
            p,q=points[a],points[b];v=None if p is None or q is None else [q[0]-p[0],q[1]-p[1]];length=math.hypot(*v) if v else 0
            r['directions'][name]=dict(available=length>0,vector=[x/length for x in v] if length else None)
        records.append(r);hashes[r['image']]=sha(ROOT/r['image'])
        if 'original' in s:hashes[s['original']]=s['original_sha256']
    for path in [PREVIOUS/'dataset.json',PREVIOUS/'protocol.json',OUT/'selection.json',OUT/'crop_proposals.json',*sorted((OUT/'labels').glob('batch-*.txt'))]:
        hashes[path.relative_to(ROOT).as_posix()]=sha(path)
    hashes['models/twilight_detector_v3/best.pt']=read(OUT/'crop_proposals.json')['detector_sha256']
    seen={}
    for r in records:
        h=sha(ROOT/r['image']);assert h not in seen,(r['frame_id'],seen.get(h));seen[h]=r['frame_id']
    protocol=dict(status='fixed_before_training',regimes=['n103','n203','n303'],arms=['keypoint_heatmap','direct_vector'],seeds=[11,29,47],
                  steps=1200,batch=12,validation_every_steps=60,image_size=224,agent_weight=.5,
                  optimizer='same as direction_expanded_train: AdamW backbone 1e-4, heads 1e-3, wd .001, clip5; cosine over 1200 updates to5e-6',
                  sampling='independent seeded shuffled cycles without replacement; full 12-image minibatches across cycle boundaries; same batch and augmentation sequence for paired arms',
                  selection='best angular error on unchanged 4 human validation images; also report final-step checkpoint as predeclared secondary',
                  nested_subset='100 of 200 additions, random seed20261009, choose5 in each consecutive temporal group of10; same subset across all training seeds',
                  evaluation='unchanged12 human reference and16 agent reference, already examined previously; never used for selection; no new blind or human-verified test',
                  purpose='annotation volume with exactly equal optimizer updates/exposures; compare both output representations',
                  limitations=['single training episode','quantity includes greater pose diversity, not pure duplication','AI label proportion increases with size','training subsets nested, one sampling draw','same character, reused small human test','manual visual agent labels awaiting user review'])
    write(OUT/'agent_labels_percent.json',dict(status='unreviewed_experimental_only',method='manual visual annotation from original crop grids; detector used only for boxes, not keypoints',frames=list(labels.values())))
    write(OUT/'dataset.json',dict(records=records,edges=EDGES,direction_names=NAMES,source_hashes=hashes,evaluation_note=protocol['evaluation']))
    write(OUT/'protocol.json',protocol)
    grids(selected,labels)
    print(Counter(r['split'] for r in records))
    print({g:sum(g in r['regimes'] for r in records) for g in protocol['regimes']})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['select','partial','build']);a=p.parse_args()
    select() if a.action=='select' else build(a.action=='partial')
