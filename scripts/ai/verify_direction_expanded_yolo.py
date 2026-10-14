"""Re-score/reload the saved YOLO checkpoint with raw keypoint coordinates."""
import sys
sys.dont_write_bytecode=True
import copy
import numpy as np
from direction_expanded_yolo import evaluate_yolo
from direction_expanded_data import ROOT,OUT,read,write,sha


def main():
    import torch
    from ultralytics import YOLO
    from direction_yolo_raw_predictor import RawPosePredictor
    torch.set_num_threads(4)
    # A low-confidence point must retain its true prediction for angle scoring.
    pred=torch.zeros((1,6+21*3));pred[0,:6]=torch.tensor([0,0,320,320,.9,0])
    pred[0,6:]=torch.tensor([[160.,80.,.1]]*21).flatten()
    predictor=RawPosePredictor()
    class SyntheticModel:
        names={0:'twilight'};kpt_shape=[21,3]
    predictor.model=SyntheticModel()
    image=torch.zeros((1,3,320,320));original=np.zeros((320,320,3),dtype=np.uint8)
    result=predictor.construct_result(pred,image,original,'synthetic.png')
    assert torch.allclose(result.keypoints.data[0,:,0],torch.full((21,),160.))
    assert torch.allclose(result.keypoints.data[0,:,2],torch.full((21,),.1))
    empty=predictor.construct_result(torch.zeros((0,6+21*3)),image,original,'empty.png')
    assert len(empty.boxes)==0
    folder=OUT/'runs/yolo_reference_s11';data=read(OUT/'dataset.json')
    old=read(folder/'result.json');new=copy.deepcopy(old)
    new['evaluation_coordinates']='Raw predictions before the Ultralytics 8.3.75 confidence<0.5 display filter; reference availability only.'
    for path,h in data['source_hashes'].items():assert sha(ROOT/path)==h,path
    reloaded=[]
    for repeat in range(2):
        model=YOLO(str(folder/'checkpoint.pt'))
        ev={s:evaluate_yolo(model,[r for r in data['records'] if r['split']==s]) for s in ['test','challenge_agent_reference']}
        reloaded.append(ev)
    differences={}
    for split in reloaded[0]:
        differences[split]={}
        for field in ['vectors','availability','points_letterbox']:
            diff=float(np.abs(np.array(reloaded[0][split][field])-np.array(reloaded[1][split][field])).max())
            assert diff<=1e-6,(split,field,diff)
            differences[split][field]=diff
    new['evaluations']=reloaded[0]
    if 'evaluation_coordinates' not in old:
        backup=folder/'result_before_raw_coordinate_fix.json'
        if backup.exists():raise RuntimeError('Refuse to overwrite original evaluation evidence')
        write(backup,old)
    write(folder/'result.json',new)
    for path,h in data['source_hashes'].items():assert sha(ROOT/path)==h,path
    write(OUT/'yolo_reload_verification.json',dict(checkpoint_sha256=sha(folder/'checkpoint.pt'),
        reloads=2,differences=differences,source_files_checked=len(data['source_hashes']),
        low_confidence_synthetic_check='passed; raw xy and confidence preserved',
        note='The first training process loaded its evaluation function before the display-filter issue was identified. Its initial result is retained; final metrics use this independently reloaded raw-coordinate evaluation. No retraining or test-based checkpoint selection.'))
    print({s:e['metrics']['mae_deg'] for s,e in new['evaluations'].items()},flush=True)


if __name__=='__main__':main()
