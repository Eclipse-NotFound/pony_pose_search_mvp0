"""Build the offline, diagram-first project explanation from frozen evidence."""
from pathlib import Path
import base64
import csv
import hashlib
import io
import json
import os
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/project-explainer'
EXP = ROOT / 'experiments/direction_scaling_20261009'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def picture(path, bound=(900, 650)):
    with Image.open(path) as im:
        im = im.convert('RGB')
        im.thumbnail(bound)
        buffer = io.BytesIO()
        im.save(buffer, 'JPEG', quality=87, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def charts(rows, mobile=False):
    os.environ['MPLCONFIGDIR'] = str(OUT / 'qa/mpl-config')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams.update({'font.family': font.get_name(), 'font.size': 11 if mobile else 13,
                         'axes.unicode_minus': False, 'svg.fonttype': 'none'})
    encoded = {}
    for selection in ['best', 'final']:
        fig, ax = plt.subplots(figsize=(3.6, 4.2) if mobile else (6.4, 4.6))
        fig.patch.set_facecolor('#fffdf9')
        ax.set_facecolor('#fffdf9')
        for arm, color, marker, label in [('keypoint_heatmap', '#7755a4', 'o', '关键点 → 方向'),
                                          ('direct_vector', '#087d80', 's', '直接预测方向')]:
            rr = [next(r for r in rows if r['selection'] == selection and r['split'] == 'test'
                       and r['arm'] == arm and r['train_images'] == n) for n in [103, 203, 303]]
            for seed in range(3):
                ax.plot([103, 203, 303], [r['per_seed_mae'][seed] for r in rr], color=color, alpha=.15, lw=1)
            ax.errorbar([103, 203, 303], [r['mae_deg'] for r in rr],
                        yerr=[r['seed_sd'] for r in rr], color=color, marker=marker,
                        markersize=7, capsize=5, lw=2, label=label)
        ax.set_ylim(0, 35); ax.set_xlim(80, 326)
        ax.set_xticks([103, 203, 303]); ax.set_yticks([0, 10, 20, 30])
        ax.set_xlabel('训练图片数（张）', labelpad=9)
        ax.set_ylabel('方向误差（度）↓ 越小越好', labelpad=10)
        ax.spines[['top', 'right']].set_visible(False)
        ax.spines[['left', 'bottom']].set_color('#9da99f')
        ax.grid(axis='y', color='#dde2d9', lw=.7); ax.set_axisbelow(True)
        fig.legend(loc='upper center', ncol=1 if mobile else 2, frameon=False,
                   bbox_to_anchor=(.58 if mobile else .54, 1.01), fontsize=10.5 if mobile else 12)
        fig.tight_layout(rect=(0, 0, 1, .84 if mobile else .93))
        suffix = '-mobile' if mobile else ''
        path = OUT / f'human-directions-{selection}{suffix}.png'
        fig.savefig(path, dpi=170)
        if not mobile:
            fig.savefig(OUT / f'human-directions-{selection}.pdf')
        plt.close(fig)
        encoded[selection] = 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
    return encoded


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = read(EXP / 'dataset.json')
    chosen = []
    paths = [EXP / 'dataset.json', EXP / 'summary.json',
             ROOT / 'data/meta/keypoint_schemas.json',
             ROOT / 'scripts/common/pose_vector_utils.py',
             ROOT / 'scripts/m08/search_similar_poses.py',
             ROOT / 'scripts/ai/direction_expanded_train.py',
             ROOT / '开发/验证记录-2026-10-09-三档标注规模对照.md']
    for sec in [20, 24, 1093]:
        rec = next(r for r in data['records'] if r['frame_id'] == f's01e15_t{sec:06d}_f000')
        chosen.append({k: rec[k] for k in ['frame_id', 'points', 'size', 'directions', 'source']})
        chosen[-1]['image'] = picture(ROOT / rec['image'])
        chosen[-1]['time'] = f'{sec//60:02}:{sec%60:02}'
        paths.append(ROOT / rec['image'])
    frame = ROOT / 'frames/s01/e15/s01e15_t000020_f000.png'
    paths.append(frame)
    with (ROOT / 'bboxes/twilight_unicorn/s01/bboxes_twilight_unicorn_s01e15.csv').open(encoding='utf-8-sig', newline='') as f:
        box = next(r for r in csv.DictReader(f) if r['frame_id'] == 's01e15_t000020_f000')
    payload = dict(examples=chosen, edges=data['edges'], names=data['direction_names'],
                   frame=picture(frame, (1200, 675)), frameSize=[1920, 1080],
                   bbox=[int(box[k]) for k in ['x1', 'y1', 'x2', 'y2']],
                   results=read(EXP / 'summary.json')['rows'])
    payload['charts'] = charts(payload['results'])
    payload['mobileCharts'] = charts(payload['results'], mobile=True)
    template = Path(__file__).with_name('project_explainer.template.html').read_text(encoding='utf-8')
    assert template.count('__DATA__') == 1
    OUT.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    artifact = OUT / 'index.html'
    artifact.write_text(template.replace('__DATA__', encoded), encoding='utf-8', newline='\n')
    paths.extend([Path(__file__), Path(__file__).with_name('project_explainer.template.html')])
    manifest = dict(created='2026-10-10', evidence_date='2026-10-09',
                    artifact='docs/project-explainer/index.html',
                    artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    source_hashes={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                    note='Offline explanation; examples use unreviewed AI references. No training, search, annotation approval, or production changes.')
    (OUT / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(f'{artifact}: {artifact.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
