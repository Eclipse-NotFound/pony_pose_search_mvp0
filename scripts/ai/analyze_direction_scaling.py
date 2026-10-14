"""Descriptive learning-curve analysis, with no feedback into training."""
import sys
sys.dont_write_bytecode = True
import numpy as np
from direction_scaling_select import OUT
from direction_pilot_data import read, write, NAMES


def main():
    runs = [read(p) for p in sorted((OUT/'runs').glob('*/result.json'))]
    assert len(runs)==18
    pairs = []; by_image = []
    for kind in ['best','final']:
        for split in ['test','challenge_agent_reference']:
            rr = {}; evs = {}
            for regime in ['n103','n203','n303']:
                for arm in ['keypoint_heatmap','direct_vector']:
                    vals=sorted([r for r in runs if r['regime']==regime and r['arm']==arm],key=lambda r:r['seed'])
                    evs[regime,arm]=[r['checkpoints'][kind]['evaluations'][split] for r in vals]
                    rr[regime,arm]=np.asarray([e['metrics']['per_image'] for e in evs[regime,arm]])
            ids=evs['n103','keypoint_heatmap'][0]['frame_ids']; groups=[]
            for i,fid in enumerate(ids):
                if groups and int(fid[8:14])-int(ids[groups[-1][-1]][8:14])<=12: groups[-1].append(i)
                else: groups.append([i])
            comparisons=[]
            for arm in ['keypoint_heatmap','direct_vector']:
                for before,after in [('n103','n203'),('n203','n303'),('n103','n303')]:
                    comparisons.append((f'{arm}: {after} minus {before}',rr[after,arm]-rr[before,arm]))
            for regime in ['n103','n203','n303']:
                comparisons.append((f'{regime}: direct minus keypoint',rr[regime,'direct_vector']-rr[regime,'keypoint_heatmap']))
            for label,delta in comparisons:
                rng=np.random.default_rng(7091); means=delta.mean(0); boot=[]
                for _ in range(5000):
                    indices=[i for g in rng.integers(0,len(groups),len(groups)) for i in groups[g]]
                    boot.append(float(means[indices].mean()))
                pairs.append(dict(selection=kind,split=split,comparison=label,delta_deg=float(delta.mean()),
                    per_seed_delta=delta.mean(1).tolist(),improved_seed_count=int((delta.mean(1)<0).sum()),
                    time_groups=[[ids[i] for i in g] for g in groups],
                    conditional_time_group_interval95=np.quantile(boot,[.025,.975]).tolist()))
            for i,fid in enumerate(ids):
                by_image.append(dict(selection=kind,split=split,frame_id=fid,
                    mean_errors={f'{g}_{a}':float(v[:,i].mean()) for (g,a),v in rr.items()}))
    chosen=[]
    for regime in ['n103','n203','n303']:
        for arm in ['keypoint_heatmap','direct_vector']:
            # Preview chosen using validation only; main results average every seed.
            r=min((r for r in runs if r['regime']==regime and r['arm']==arm),
                  key=lambda r:r['checkpoints']['best']['evaluations']['val']['metrics']['mae_deg'])
            chosen.append(dict(regime=regime,arm=arm,seed=r['seed'],step=r['checkpoints']['best']['step'],
                validation_mae=r['checkpoints']['best']['evaluations']['val']['metrics']['mae_deg'],
                human_mae=r['checkpoints']['best']['evaluations']['test']['metrics']['mae_deg']))
    report=dict(comparisons=pairs,per_image=by_image,preview_models=chosen,
        total_training_seconds=sum(r['train_seconds'] for r in runs),
        total_run_seconds=sum(r['seconds'] for r in runs),
        note='Conditional intervals resample time groups after averaging seeds. Reused 12 human and 16 unreviewed agent references; not population intervals or new blind evidence. One nested subset draw; label noise and episode dependence not covered.')
    write(OUT/'analysis.json',report)
    for row in read(OUT/'summary.json')['rows']:
        if row['split'] in ['test','challenge_agent_reference']:
            print(row['selection'],row['split'],row['regime'],row['arm'],round(row['mae_deg'],3),round(row['seed_sd'],3),flush=True)


if __name__=='__main__': main()
