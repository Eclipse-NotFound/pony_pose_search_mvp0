"""Reload all completed matched runs and check retained source files."""
import sys
sys.dont_write_bytecode = True
import gc
import numpy as np
import torch
from direction_expanded_train import PoseNet, tensor_data, evaluate
from direction_expanded_data import ROOT, OUT, read, write, sha


def main():
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    data = read(OUT/'dataset.json')
    for path, expected in data['source_hashes'].items():
        assert sha(ROOT/path) == expected, path
    x, t = tensor_data(data['records'], 'cuda')
    checked = []
    for path in sorted((OUT/'runs').glob('*/checkpoint.pt')):
        if path.parent.name.startswith('yolo_'):
            continue
        saved = torch.load(path, map_location='cpu', weights_only=True)
        assert saved['dataset_sha256'] == sha(OUT/'dataset.json')
        assert saved['protocol_sha256'] == sha(OUT/'protocol.json')
        net = PoseNet(saved['arm'], pretrained=False).cuda().eval()
        net.load_state_dict(saved['state_dict'])
        result = read(path.parent/'result.json')
        differences = {}
        for split in ['test', 'challenge_agent_reference']:
            idx = [i for i,r in enumerate(data['records']) if r['split'] == split]
            actual = evaluate(net, x, t, idx, data['records'])
            expected = result['evaluations'][split]
            delta = {}
            for field in ['vectors', 'availability', 'points_letterbox']:
                if actual[field] is None:
                    assert expected[field] is None
                    continue
                delta[field] = float(np.abs(np.array(actual[field])-np.array(expected[field])).max())
                assert delta[field] <= 1e-6, (path, split, field, delta[field])
            assert actual['metrics']['mae_deg'] == expected['metrics']['mae_deg']
            differences[split] = delta
        checked.append(dict(run=path.parent.name, checkpoint_sha256=sha(path), differences=differences))
        print('verified '+path.parent.name, flush=True)
        del net, saved
        gc.collect()
        torch.cuda.empty_cache()
    assert len(checked) == 12
    for path, expected in data['source_hashes'].items():
        assert sha(ROOT/path) == expected, path
    write(OUT/'reload_verification.json', dict(runs=checked, source_files_checked=len(data['source_hashes']),
        source_integrity='all unchanged before and after', torch=torch.__version__,
        dataset_sha256=sha(OUT/'dataset.json'), protocol_sha256=sha(OUT/'protocol.json')))


if __name__ == '__main__':
    main()
