"""Describe the frozen corpus, including label availability and repeated time ranges."""
import sys
sys.dont_write_bytecode = True
from collections import Counter
from direction_scaling_select import OUT, PREVIOUS
from direction_pilot_data import ROOT, NAMES, read, write, sha


def describe(records):
    times = sorted(int(r['frame_id'][8:14]) for r in records)
    return dict(images=len(records),sources=dict(Counter(r['source'] for r in records)),
                labels=sum(sum(p is not None for p in r['points']) for r in records),
                directions=sum(sum(v['available'] for v in r['directions'].values()) for r in records),
                direction_coverage={n:sum(r['directions'][n]['available'] for r in records) for n in NAMES},
                adjacent_time_gaps_at_most_2s=sum(b-a<=2 for a,b in zip(times,times[1:])),
                temporal_groups_gap_over_12s=1+sum(b-a>12 for a,b in zip(times,times[1:])) if times else 0,
                zero_direction_images=[r['frame_id'] for r in records if not any(v['available'] for v in r['directions'].values())])


def main():
    data=read(OUT/'dataset.json'); protocol=read(OUT/'protocol.json')
    for p,h in data['source_hashes'].items(): assert sha(ROOT/p)==h,p
    records=data['records']; new=[r for r in records if r['source']=='agent_scaling_visual_20261009']
    assert len(new)==200 and len({sha(ROOT/r['image']) for r in records})==335
    report=dict(regimes={g:describe([r for r in records if g in r['regimes']]) for g in protocol['regimes']},
                new=describe(new),split_counts=dict(Counter(r['split'] for r in records)),
                protected_source_files=len(data['source_hashes']),unique_image_contents=335,
                previous_dataset_sha256=sha(PREVIOUS/'dataset.json'),dataset_sha256=sha(OUT/'dataset.json'),
                exact_duplicates=0,new_existing_crops=40,new_full_frame_crops=160,
                note='Time groups are descriptive, not manually verified scene identities; adjacent training frames and reused animation poses remain. All test/challenge images are from episode24, all added training from episode15.')
    write(OUT/'data_audit.json',report)
    write(OUT/'annotation_qa.json',dict(status='agent_self_checked_not_user_approved',
        images=200,original_visual_label_grids=50,overlay_pages_reviewed=list(range(1,51)),
        review_method='Original crop grids visually annotated; all 200 overlays subsequently checked, first16 at full-page size and remaining184 through mosaics.',
        label_source='No pose-model predictions used; detector only proposed crop boxes.',
        frozen_dataset_sha256=sha(OUT/'dataset.json')))
    print(report)


if __name__=='__main__': main()
