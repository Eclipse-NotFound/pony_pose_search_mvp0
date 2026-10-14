"""Read-only source audit and isolated data preparation for the direction pilot."""
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments/direction_pilot_20261008"
EDGES = [(0,1),(3,2),(3,4),(19,20),(5,6),(6,7),(8,9),(9,10),(11,12),(12,13),(13,14),(15,16),(16,17),(17,18)]
NAMES = ["head","neck","body","tail","front1_upper","front1_lower","front2_upper","front2_lower","back1_upper","back1_middle","back1_lower","back2_upper","back2_middle","back2_lower"]
NEW_TIMES = [51,90,103,116,139,154,164,174,193,217,399,413,470,983,1062,1207]

def read(p): return json.loads(p.read_text(encoding="utf-8"))
def write(p,d): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def crop(fid): return ROOT/f"crops/twilight_unicorn/s01/{fid[3:6]}/{fid}_twilight_unicorn_001.png"
def flat(k):
    return [k.get("head",{}).get(x) for x in ["head_center","head_front","neck"]]+[k.get("body",{}).get(x) for x in ["body_1","body_2"]]+[leg.get(x) for group,fields in [("front_legs",["base","mid","end"]),("back_legs",["base","knee","mid","end"])] for leg in k[group] for x in fields]+[k.get("tail",{}).get(x) for x in ["tail_base","tail_end"]]

def audit():
    if (OUT/"runs").exists():
        raise RuntimeError("This experiment has trained models; prepare a new experiment directory instead of replacing its data")
    OUT.mkdir(parents=True,exist_ok=True)
    hashes={}; records=[]
    for protected in [ROOT/"data/meta/keypoint_schemas.json",ROOT/"models/twilight_pose_v1/best.pt",*sorted((ROOT/"poses/twilight_unicorn/s01").glob("*.json"))]:
        hashes[protected.relative_to(ROOT).as_posix()]=sha(protected)
    for ep in ["s01e15","s01e24"]:
        p=ROOT/f"keypoints/twilight_unicorn/s01/keypoints_twilight_unicorn_{ep}.json"
        hashes[p.relative_to(ROOT).as_posix()]=sha(p)
        for item in read(p)["items"]:
            points=flat(item["keypoints"]); fid=item["frame_id"]
            if not any(v is not None for v in points): continue
            t=int(fid[8:14]); split="test" if ep=="s01e24" else "val" if 240<=t<=390 else "train"
            records.append(dict(frame_id=fid,points=points,split=split,source="human_official",weight=1.0))
    for folder in ["2026-09-11-01","2026-09-12-02"]:
        p=ROOT/f"suggestions/review_batches/{folder}/visual_labels.json"
        hashes[p.relative_to(ROOT).as_posix()]=sha(p)
        for f in read(p)["frames"]:
            if f["frame_id"].startswith("s01e15") and not 220<=int(f["frame_id"][8:14])<=410:
                records.append(dict(frame_id=f["frame_id"],points=f["points"],split="train",source="agent_prior_draft",weight=0.5))
    p=OUT/"agent_new_labels.json"
    if p.exists():
        hashes[p.relative_to(ROOT).as_posix()]=sha(p)
        for f in read(p)["frames"]:
            assert f["frame_id"] not in {x["frame_id"] for x in records}
            assert f["frame_id"].startswith("s01e15") and not 240<=int(f["frame_id"][8:14])<=390
            records.append(dict(frame_id=f["frame_id"],points=f["points"],split="train",source="agent_new_visual",weight=0.5))
    for r in records:
        p=crop(r["frame_id"]); r["image"]=p.relative_to(ROOT).as_posix(); r["size"]=list(Image.open(p).size)
        hashes[r["image"]]=sha(p)
        assert len(r["points"])==21
        assert all(v is None or (0<=v[0]<r["size"][0] and 0<=v[1]<r["size"][1]) for v in r["points"]),r["frame_id"]
        r["directions"]={}
        for name,(a,b) in zip(NAMES,EDGES):
            p1,p2=r["points"][a],r["points"][b]
            delta=[p2[0]-p1[0],p2[1]-p1[1]] if p1 is not None and p2 is not None else None
            n=math.hypot(*delta) if delta is not None else 0
            r["directions"][name]={"available":n>0,"vector":[v/n for v in delta] if n>0 else None}
    # Every evaluation frame remains human-authored; agent drafts never enter val/test.
    assert all(r["source"]=="human_official" for r in records if r["split"]!="train")
    for s1,s2 in [("train","val"),("train","test"),("val","test")]:
        assert not ({hashes[r["image"]] for r in records if r["split"]==s1}&{hashes[r["image"]] for r in records if r["split"]==s2})
    write(OUT/"dataset.json",dict(direction_names=NAMES,edges=EDGES,records=records,source_hashes=hashes))
    protocol=dict(status="fixed_before_training",representation="14 directed 2D unit vectors in image pixel axes (x right, y down)",split="train: episode15 outside 240..390s; validation: episode15 240..390s; final test: all episode24 human labels",agent_data="train only, weight 0.5, unreviewed experimental labels; never official",arms=["keypoint regression then direction conversion","keypoint regression with additional angular loss","direct direction regression"],regimes=["human_only","human_plus_agent"],shared_encoder="frozen ImageNet ResNet18, spatial 2x2 pooling, identical image features",head="2048 -> 128 ReLU dropout0.1 -> geometry and 14 availability logits",seeds=[11,29,47],epochs=300,learning_rate=0.001,weight_decay=0.001,loss="4*masked_coordinate_MSE for keypoint; plus 1-dot for keypoint_angle; 1-dot for direct; all add 0.05 visibility BCE; whole-leg permutations minimized jointly",selection="validation angular error every 5 epochs only; no final test used for selection",primary="image-macro mean angular error over human-available directions, whole-leg permutation allowed; no predicted-confidence filtering",secondary=["fraction within 15 and 30 degrees","per-component angular error","availability precision/recall descriptive only; separate matched head per arm"],limits=["small sample, one held-out episode","frozen-feature pilot, not YOLO versus replacement production benchmark","legacy human direction conventions may be inconsistent","no 3D inference","does not measure actual query relevance or human review time"])
    write(OUT/"protocol.json",protocol)
    print(json.dumps({s:sum(r["split"]==s for r in records) for s in ["train","val","test"]}))
    for page in range(2):
        canvas=Image.new("RGB",(1280,1080),(242,242,242));d=ImageDraw.Draw(canvas)
        for j,t in enumerate(NEW_TIMES[page*8:page*8+8]):
            fid=f"s01e15_t{t:06d}_f000";im=Image.open(crop(fid)).convert("RGB");size=im.size;im.thumbnail((310,500))
            x=(j%4)*320+(320-im.width)//2;y=(j//4)*540+30
            canvas.paste(im,(x,y));d.text(((j%4)*320+5,(j//4)*540+8),f"{t}s  {size[0]}x{size[1]}",fill=(0,0,0))
        canvas.save(OUT/f"new-candidates-{page+1}.jpg",quality=90)

if __name__=="__main__": audit()
