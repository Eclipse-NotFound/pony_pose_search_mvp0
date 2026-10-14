"""Fixed expanded labels and splits. Does not edit any official annotations."""
import sys
sys.dont_write_bytecode = True
import copy
import math
from pathlib import Path
from PIL import Image, ImageDraw
from direction_pilot_data import ROOT, EDGES, NAMES, read, write, sha, crop

OUT = ROOT / "experiments/direction_expanded_20261009"
OLD = ROOT / "experiments/direction_pilot_20261008"


def make_overlays(rows):
    colors = [(0, 125, 245), (15, 160, 195), (227, 177, 0), (227, 177, 0),
              (20, 200, 90), (20, 200, 90), (240, 127, 10), (240, 127, 10)] + [(230, 32, 183)] * 3 + [(20, 190, 216)] * 3
    for page in range(math.ceil(len(rows) / 4)):
        canvas = Image.new("RGB", (1280, 1120), "white")
        d = ImageDraw.Draw(canvas)
        for j, r in enumerate(rows[page*4:page*4+4]):
            im = Image.open(ROOT / r['image']).convert('RGB')
            scale = min(590/im.width, 490/im.height)
            im = im.resize((round(im.width*scale), round(im.height*scale)))
            x = (j % 2)*640 + 30; y = (j//2)*560 + 45
            canvas.paste(im, (x, y)); d.text((x, y-25), r['frame_id'], fill='black')
            for i, (a, b) in enumerate(EDGES):
                p, q = r['points'][a], r['points'][b]
                if p is None or q is None:
                    continue
                start = (x+p[0]*scale, y+p[1]*scale); end = (x+q[0]*scale, y+q[1]*scale)
                d.line([start, end], fill=colors[i], width=3)
                ux, uy = end[0]-start[0], end[1]-start[1]; n = max(math.hypot(ux, uy), 1)
                ux /= n; uy /= n
                d.polygon([end, (end[0]-8*ux+4*uy, end[1]-8*uy-4*ux),
                           (end[0]-8*ux-4*uy, end[1]-8*uy+4*ux)], fill=colors[i])
        canvas.save(OUT / f'annotation-check-{page+1:02}.jpg', quality=93)


def build():
    if (OUT / 'runs').exists():
        raise RuntimeError('Do not replace a trained experiment dataset')
    old = read(OLD / 'dataset.json')
    for path, expected in old['source_hashes'].items():
        assert sha(ROOT / path) == expected, path
    records = copy.deepcopy(old['records']); hashes = dict(old['source_hashes'])
    for r in records:
        r['regimes'] = ['base55', 'expanded103'] if r['split'] == 'train' else []
    selection = {f['frame_id']: f['split'] for f in read(OUT/'selection.json')['frames']}
    labels = read(OUT / 'agent_labels_percent.json')
    assert len(labels['frames']) == 64 and len(selection) == 64
    for f in labels['frames']:
        fid = f['frame_id']; path = crop(fid)
        with Image.open(path) as im:
            w, h = im.size
        assert len(f['points_percent']) == 21
        pts = [None if p is None else [round(p[0]*w/100, 2), round(p[1]*h/100, 2)] for p in f['points_percent']]
        assert all(p is None or (0 <= p[0] < w and 0 <= p[1] < h) for p in pts)
        split = selection[fid]
        records.append(dict(frame_id=fid, image=path.relative_to(ROOT).as_posix(), size=[w,h], points=pts,
                            split=split, source='agent_new_visual_20261009', weight=.5,
                            regimes=['expanded103'] if split == 'train' else [], notes=f['notes']))
    assert len({r['frame_id'] for r in records}) == len(records)
    for r in records:
        hashes[r['image']] = sha(ROOT / r['image'])
        r['directions'] = {}
        for name, (a, b) in zip(NAMES, EDGES):
            p, q = r['points'][a], r['points'][b]
            delta = None if p is None or q is None else [q[0]-p[0], q[1]-p[1]]
            length = 0 if delta is None else math.hypot(*delta)
            r['directions'][name] = dict(available=length > 0, vector=[x/length for x in delta] if length > 0 else None)
    for path in [OLD/'dataset.json', OLD/'protocol.json', OUT/'selection.json', OUT/'agent_labels_percent.json']:
        hashes[path.relative_to(ROOT).as_posix()] = sha(path)
    splits = ['train', 'val', 'test', 'challenge_agent_reference']
    for i, a in enumerate(splits):
        for b in splits[i+1:]:
            assert not ({hashes[r['image']] for r in records if r['split']==a} & {hashes[r['image']] for r in records if r['split']==b})
    assert all(r['source']=='human_official' for r in records if r['split'] in ['val','test'])
    data = dict(records=records, edges=EDGES, direction_names=NAMES, source_hashes=hashes,
                evaluation_note='12 human reference images were examined in the prior experiment; not a new blind test. 16 new agent challenge references are provisional and reported separately.')
    protocol = dict(status='fixed_before_training', arms=['keypoint_heatmap','direct_vector'],
                    regimes=['base55','expanded103'], seeds=[11,29,47], epochs=80, batch=12,
                    image_size=224, backbone='ImageNet ResNet18; all layers fine-tuned; backbone batchnorm running statistics frozen',
                    head='keypoints: 28x28 spatial probability maps and soft-argmax; directions: spatial 2x2 pooling and MLP',
                    optimization='AdamW; backbone lr 0.0001; heads lr 0.001; weight_decay 0.001; cosine schedule; clip_grad_norm 5',
                    augmentation='independent seeded data stream; horizontal flip and brightness 0.85..1.15; no final evaluation augmentation',
                    loss='heatmap normalized Gaussian cross-entropy + 4*coordinate MSE; direct 1-dot; both +0.1*availability BCE; minimize whole-leg permutations jointly',
                    agent_weight=.5, selection='every 5 epochs on 4 human validation images; lowest per-image angular error; test/challenge unused for selection',
                    primary='per-image average 2D angular error on human-defined available directions, whole-leg swaps allowed; no model confidence filtering',
                    secondary=['per-direction error and <=15/30deg','component angles','availability precision/recall','keypoint PCK at 5% crop max dimension only for keypoint model'],
                    yolo_reference='optional separate practical baseline: YOLOv8n-Pose initialized from COCO pose, custom 21 points, expanded103, seed11, 80 epochs, 320px. Different architecture/pretraining: not a causal comparison of output type.',
                    limits=['small single-character/two-episode dataset','12 human test images reused from previous experiment','agent annotations remain unreviewed','16 challenge references are not human ground truth','no claim about retrieval quality'])
    write(OUT/'dataset.json', data); write(OUT/'protocol.json', protocol)
    write(OUT/'agent_new_labels.json', dict(status=labels['status'], frames=[r for r in records if r['source']=='agent_new_visual_20261009']))
    make_overlays([r for r in records if r['source']=='agent_new_visual_20261009'])
    print({s: sum(r['split']==s for r in records) for s in splits})


if __name__ == '__main__':
    build()
