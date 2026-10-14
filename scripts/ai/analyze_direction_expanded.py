"""Descriptive paired comparisons; never feeds back into model selection."""
import sys
sys.dont_write_bytecode=True
import numpy as np
from direction_expanded_data import OUT, read, write


def main():
    runs=[read(p) for p in (OUT/'runs').glob('*_s*/result.json') if not p.parent.name.startswith('yolo_')]
    comparison=[]
    for split in ['test','challenge_agent_reference']:
        rr={}
        for regime in ['base55','expanded103']:
            for arm in ['keypoint_heatmap','direct_vector']:
                vals=[r for r in runs if r['regime']==regime and r['arm']==arm]
                rr[(regime,arm)]=np.array([r['evaluations'][split]['metrics']['per_image'] for r in sorted(vals,key=lambda r:r['seed'])])
        pairs=[('expanded model: direct minus keypoints',rr['expanded103','direct_vector']-rr['expanded103','keypoint_heatmap']),
               ('keypoints: expanded minus base',rr['expanded103','keypoint_heatmap']-rr['base55','keypoint_heatmap']),
               ('direct: expanded minus base',rr['expanded103','direct_vector']-rr['base55','direct_vector'])]
        ids=runs[0]['evaluations'][split]['frame_ids']
        groups=[]
        for i,fid in enumerate(ids):
            if groups and int(fid[8:14])-int(ids[groups[-1][-1]][8:14])<=12:
                groups[-1].append(i)
            else:groups.append([i])
        for label,delta in pairs:
            rng=np.random.default_rng(7091);means=delta.mean(0);boot=[]
            for _ in range(5000):
                indices=[i for g in rng.integers(0,len(groups),len(groups)) for i in groups[g]]
                boot.append(means[indices].mean())
            comparison.append(dict(split=split,comparison=label,delta_deg=float(delta.mean()),
                per_seed_delta=delta.mean(1).tolist(),scene_groups=len(groups),
                conditional_scene_interval95=np.quantile(boot,[.025,.975]).tolist()))
    selection=[]
    for arm in ['keypoint_heatmap','direct_vector']:
        r=min((r for r in runs if r['regime']=='expanded103' and r['arm']==arm),key=lambda r:r['val_mae_deg'])
        selection.append(dict(arm=arm,seed=r['seed'],best_epoch=r['best_epoch'],validation_mae=r['val_mae_deg'],
            human_mae=r['evaluations']['test']['metrics']['mae_deg'],challenge_mae=r['evaluations']['challenge_agent_reference']['metrics']['mae_deg']))
    report=dict(comparisons=comparison,preview_models=selection,total_training_seconds=sum(r['seconds'] for r in runs),
        note='Conditional descriptive intervals resample time groups after averaging the three seeds. Small reused human set / unreviewed agent reference; not population confidence or an independent generalization claim.')
    write(OUT/'analysis.json',report)
    print(report)


if __name__=='__main__':main()
