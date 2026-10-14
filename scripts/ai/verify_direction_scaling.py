"""Reload both saved selections for all 18 runs; audit equal-compute pairing."""
import sys
sys.dont_write_bytecode = True
import gc
from pathlib import Path
import numpy as np
import torch
from direction_scaling_train import verify_sources
from direction_scaling_select import OUT
from direction_expanded_train import PoseNet, tensor_data, evaluate, read, write, sha


def main():
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    data = read(OUT/'dataset.json'); protocol = read(OUT/'protocol.json')
    manifest = read(OUT/'training_manifest.json'); verify_sources(data, manifest)
    results = [read(p) for p in sorted((OUT/'runs').glob('*/result.json'))]
    expected_keys = {(g,a,s) for g in protocol['regimes'] for a in protocol['arms'] for s in protocol['seeds']}
    assert {(r['regime'],r['arm'],r['seed']) for r in results} == expected_keys
    assert len(results) == 18
    for r in results:
        assert r['manifest'] == manifest
        assert r['steps'] == protocol['steps'] == 1200 and r['batch'] == 12
        assert r['exposures'] == sum(r['exposure_counts'].values()) == 14400
        assert len(r['exposure_counts']) == r['train_images']
        assert max(r['exposure_counts'].values())-min(r['exposure_counts'].values()) <= 1
        assert [p['step'] for p in r['trace']] == list(range(60,1201,60))
        assert r['checkpoints']['best']['step'] == min(r['trace'], key=lambda p:p['val_mae_deg'])['step']
        assert r['checkpoints']['final']['step'] == 1200
    pairs = []
    for regime in protocol['regimes']:
        for seed in protocol['seeds']:
            pair = [r for r in results if r['regime']==regime and r['seed']==seed]
            assert len(pair)==2
            for key in ['sample_order_sha256','augmentation_rng_final','exposure_counts']:
                assert pair[0][key]==pair[1][key], (regime, seed, key)
            pairs.append(dict(regime=regime,seed=seed,sample_order_sha256=pair[0]['sample_order_sha256']))
    x, t = tensor_data(data['records'], 'cuda'); checked = []
    for result in results:
        folder = OUT/'runs'/f'{result["regime"]}_{result["arm"]}_s{result["seed"]}'
        for kind in ['best','final']:
            path = folder/f'{kind}.pt'
            assert sha(path) == result['checkpoints'][kind]['sha256']
            saved = torch.load(path,map_location='cpu',weights_only=True)
            assert saved['manifest']==manifest and saved['selection']==kind
            assert saved['step']==result['checkpoints'][kind]['step']
            net = PoseNet(saved['arm'],pretrained=False).cuda().eval()
            net.load_state_dict(saved['state_dict']); differences = {}
            for split in ['val','test','challenge_agent_reference']:
                idx = [i for i,r in enumerate(data['records']) if r['split']==split]
                actual = evaluate(net,x,t,idx,data['records'])
                expected = result['checkpoints'][kind]['evaluations'][split]
                assert actual['frame_ids']==expected['frame_ids']
                delta = {}
                for field in ['vectors','availability','points_letterbox']:
                    if actual[field] is None:
                        assert expected[field] is None
                        continue
                    delta[field] = float(np.abs(np.asarray(actual[field])-np.asarray(expected[field])).max())
                    assert delta[field] <= 1e-6, (path,split,field,delta[field])
                assert actual['metrics']['mae_deg']==expected['metrics']['mae_deg']
                differences[split] = delta
            checked.append(dict(run=folder.name,selection=kind,checkpoint_sha256=sha(path),differences=differences))
            print('verified '+folder.name+' '+kind,flush=True)
            del net,saved; gc.collect(); torch.cuda.empty_cache()
    verify_sources(data,manifest)
    write(OUT/'reload_verification.json',dict(runs=18,checkpoints=checked,paired_schedules=pairs,
          source_files_checked=len(data['source_hashes']),source_integrity='all unchanged before and after',
          manifest=manifest,verifier_sha256=sha(Path(__file__))))


if __name__=='__main__': main()
