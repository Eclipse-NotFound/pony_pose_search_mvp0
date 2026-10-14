"""Fixed-update, nested annotation-volume comparison. Experiment outputs only."""
import sys
sys.dont_write_bytecode = True
import argparse
from collections import Counter
import gc
import hashlib
import math
import random
import time
import numpy as np
import torch
from torch import nn
from direction_scaling_select import OUT
from direction_expanded_train import (ROOT, SIZE, WEIGHTS, PoseNet, read, write, sha,
    tensor_data, augment, normalize_image, objective, evaluate)


class ShuffledCycles:
    """Full batches across epoch boundaries; every completed cycle visits each item."""
    def __init__(self, indices, seed):
        self.indices = list(indices)
        if not self.indices:
            raise ValueError('Empty training set')
        self.rng = np.random.default_rng(seed)
        self.pending = []

    def take(self, count):
        while len(self.pending) < count:
            self.pending.extend(self.rng.permutation(self.indices).tolist())
        batch, self.pending = self.pending[:count], self.pending[count:]
        return batch


def source_manifest(data, protocol):
    code = ['direction_scaling_train.py', 'direction_scaling_select.py',
            'direction_scaling_data.py', 'direction_expanded_train.py',
            'direction_expanded_data.py', 'direction_pilot.py', 'direction_pilot_data.py']
    return dict(dataset_sha256=sha(OUT/'dataset.json'), protocol_sha256=sha(OUT/'protocol.json'),
                encoder_weights_sha256=sha(WEIGHTS),
                code_hashes={f'scripts/ai/{p}': sha(ROOT/'scripts/ai'/p) for p in code},
                torch=str(torch.__version__), cuda=torch.version.cuda,
                gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)


def verify_sources(data, manifest):
    for path, h in data['source_hashes'].items():
        assert sha(ROOT/path) == h, path
    for path, h in manifest['code_hashes'].items():
        assert sha(ROOT/path) == h, path
    assert sha(OUT/'dataset.json') == manifest['dataset_sha256']
    assert sha(OUT/'protocol.json') == manifest['protocol_sha256']
    assert sha(WEIGHTS) == manifest['encoder_weights_sha256']


def train_one(x, t, records, arm, regime, seed, device, protocol, manifest):
    folder = OUT/'runs'/f'{regime}_{arm}_s{seed}'
    if (folder/'result.json').exists():
        result = read(folder/'result.json')
        assert result['manifest'] == manifest, folder
        for kind, result_checkpoint in result['checkpoints'].items():
            assert sha(folder/f'{kind}.pt') == result_checkpoint['sha256']
        print('Already complete: '+folder.name, flush=True)
        return result
    if folder.exists():
        raise RuntimeError('Incomplete run requires explicit recovery: '+str(folder))
    folder.mkdir(parents=True)
    write(folder/'started.json', dict(arm=arm, regime=regime, seed=seed, manifest=manifest))
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if device == 'cuda':
        torch.cuda.manual_seed_all(seed)
    # Independent from architecture/dropout RNG, identical for paired arms.
    aug_rng = np.random.default_rng(seed+100000)
    train_idx = [i for i, r in enumerate(records) if regime in r['regimes']]
    sampler = ShuffledCycles(train_idx, seed+200000)
    val_idx = [i for i, r in enumerate(records) if r['split'] == 'val']
    net = PoseNet(arm).to(device)
    opt = torch.optim.AdamW([
        {'params': list(net.encoder.parameters()), 'lr': .0001},
        {'params': [p for n, p in net.named_parameters() if not n.startswith('encoder.')], 'lr': .001}
    ], weight_decay=.001)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=protocol['steps'], eta_min=.000005)
    best = math.inf; best_state = None; best_step = None; trace = []; block_loss = 0
    exposure = Counter(); digest = hashlib.sha256(); start = time.perf_counter()
    for step in range(1, protocol['steps']+1):
        net.train()
        ids = sampler.take(protocol['batch'])
        digest.update(np.asarray(ids, dtype='<i8').tobytes()); exposure.update(ids)
        xb, tb = augment(x[ids], {k: v[ids] for k, v in t.items()}, aug_rng)
        opt.zero_grad(set_to_none=True)
        loss = objective(net(normalize_image(xb)), tb, arm)
        if not torch.isfinite(loss):
            raise RuntimeError('Non-finite loss')
        loss.backward(); nn.utils.clip_grad_norm_(net.parameters(), 5); opt.step(); schedule.step()
        block_loss += loss.item()
        if step % protocol['validation_every_steps'] == 0:
            validation = evaluate(net, x, t, val_idx, records)
            score = validation['metrics']['mae_deg']
            trace.append(dict(step=step, loss=block_loss/protocol['validation_every_steps'], val_mae_deg=score))
            block_loss = 0
            if score < best:
                best = score; best_step = step
                best_state = {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
            if step % 240 == 0:
                print(f'{folder.name} {step}/{protocol["steps"]} val={score:.2f} best={best:.2f}', flush=True)
    assert best_state is not None
    train_seconds = time.perf_counter()-start
    final_state = {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
    result = dict(arm=arm, regime=regime, seed=seed, train_images=len(train_idx),
                  steps=protocol['steps'], batch=protocol['batch'], exposures=sum(exposure.values()),
                  exposure_counts={records[i]['frame_id']: exposure[i] for i in train_idx},
                  sample_order_sha256=digest.hexdigest(), augmentation_rng_final=aug_rng.bit_generator.state,
                  train_seconds=train_seconds, manifest=manifest, trace=trace, checkpoints={})
    # Evaluation references are first used after all updates and checkpoint selection.
    for kind, state, step in [('best', best_state, best_step), ('final', final_state, protocol['steps'])]:
        net.load_state_dict(state); net.eval()
        checkpoint = dict(state_dict=state, arm=arm, regime=regime, seed=seed, step=step,
                          image_size=SIZE, selection=kind, manifest=manifest)
        torch.save(checkpoint, folder/f'{kind}.pt')
        evaluations = {}
        for split in ['val', 'test', 'challenge_agent_reference', 'train']:
            idx = train_idx if split == 'train' else [i for i, r in enumerate(records) if r['split'] == split]
            evaluations[split] = evaluate(net, x, t, idx, records)
        result['checkpoints'][kind] = dict(step=step, sha256=sha(folder/f'{kind}.pt'), evaluations=evaluations)
    result['seconds'] = time.perf_counter()-start
    write(folder/'result.json', result)
    human = result['checkpoints']['best']['evaluations']['test']['metrics']['mae_deg']
    print(f'DONE {folder.name} human={human:.2f} seconds={result["seconds"]:.1f}', flush=True)
    del net, opt, best_state, final_state, state, checkpoint
    gc.collect()
    if device == 'cuda': torch.cuda.empty_cache()
    return result


def summarize(results, protocol, manifest):
    rows = []
    for kind in ['best', 'final']:
        for split in ['test', 'challenge_agent_reference', 'val', 'train']:
            for regime in protocol['regimes']:
                for arm in protocol['arms']:
                    rr = sorted([r for r in results if r['regime'] == regime and r['arm'] == arm], key=lambda r: r['seed'])
                    if not rr: continue
                    mm = [r['checkpoints'][kind]['evaluations'][split]['metrics'] for r in rr]
                    keys = ['mae_deg', 'micro_mae_deg', 'within15', 'within30', 'availability_precision', 'availability_recall']
                    row = dict(selection=kind, split=split, regime=regime, arm=arm,
                               train_images=rr[0]['train_images'], seeds=[r['seed'] for r in rr],
                               per_seed_mae=[m['mae_deg'] for m in mm],
                               seed_sd=float(np.std([m['mae_deg'] for m in mm])),
                               **{k: float(np.mean([m[k] for m in mm])) for k in keys})
                    row['components'] = {k: float(np.mean([m['components'][k] for m in mm])) for k in mm[0]['components']}
                    if arm == 'keypoint_heatmap':
                        row['keypoint_pck05'] = float(np.mean([m['keypoint_pck05'] for m in mm]))
                    rows.append(row)
    return dict(rows=rows, complete=len(results)==18, run_count=len(results), manifest=manifest,
                evaluation_note=protocol['evaluation'], protocol=protocol)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--device', default='cuda', choices=['cpu', 'cuda'])
    parser.add_argument('--regime', choices=['n103', 'n203', 'n303'])
    parser.add_argument('--arm', choices=['keypoint_heatmap', 'direct_vector'])
    parser.add_argument('--seed', type=int, choices=[11, 29, 47]); args = parser.parse_args()
    torch.set_num_threads(4); torch.backends.cudnn.benchmark = False; torch.backends.cudnn.deterministic = True
    if args.device == 'cuda' and not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable')
    data = read(OUT/'dataset.json'); protocol = read(OUT/'protocol.json'); manifest = source_manifest(data, protocol)
    verify_sources(data, manifest)
    frozen = OUT/'training_manifest.json'
    if frozen.exists(): assert read(frozen) == manifest
    else: write(frozen, manifest)
    print('Data/source hashes verified; loading images', flush=True)
    x, t = tensor_data(data['records'], args.device)
    for regime in ([args.regime] if args.regime else protocol['regimes']):
        for seed in ([args.seed] if args.seed else protocol['seeds']):
            for arm in ([args.arm] if args.arm else protocol['arms']):
                train_one(x, t, data['records'], arm, regime, seed, args.device, protocol, manifest)
                results = [read(p) for p in sorted((OUT/'runs').glob('*/result.json'))]
                write(OUT/'summary.json', summarize(results, protocol, manifest))
    verify_sources(data, manifest)
    print('All requested runs complete; source hashes unchanged', flush=True)


if __name__ == '__main__': main()
