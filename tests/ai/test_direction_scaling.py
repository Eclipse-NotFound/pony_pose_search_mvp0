"""Learning-curve split and equal-compute safeguards."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts/ai'))
from direction_scaling_train import ShuffledCycles
from direction_scaling_select import OUT, PREVIOUS
from direction_pilot_data import ROOT, read, sha


class ScalingProtocolTests(unittest.TestCase):
    def test_cycles_have_exact_coverage_and_full_batches(self):
        sampler = ShuffledCycles(range(103), 11)
        batches = [sampler.take(12) for _ in range(1200)]
        self.assertTrue(all(len(b) == 12 for b in batches))
        flat = np.asarray(batches).ravel().tolist()
        for offset in range(0, len(flat)-103, 103):
            self.assertEqual(sorted(flat[offset:offset+103]), list(range(103)))
        self.assertEqual(len(flat), 14400)

    def test_paired_seed_schedule_is_independent_and_reproducible(self):
        a, b = ShuffledCycles(range(203), 200011), ShuffledCycles(range(203), 200011)
        c = ShuffledCycles(range(203), 200029)
        aa = [a.take(12) for _ in range(40)]
        self.assertEqual(aa, [b.take(12) for _ in range(40)])
        self.assertNotEqual(aa, [c.take(12) for _ in range(40)])
        with self.assertRaises(ValueError): ShuffledCycles([], 1)

    def test_nested_sizes_and_reference_labels_unchanged(self):
        current, old = read(OUT/'dataset.json'), read(PREVIOUS/'dataset.json')
        records = current['records']; before = {r['frame_id']: r for r in old['records']}
        groups = [{r['frame_id'] for r in records if g in r['regimes']} for g in ['n103','n203','n303']]
        self.assertEqual([len(g) for g in groups], [103,203,303])
        self.assertTrue(groups[0] < groups[1] < groups[2])
        self.assertEqual(groups[0], {r['frame_id'] for r in old['records'] if r['split']=='train'})
        for r in records:
            if r['frame_id'] in before:
                prior = before[r['frame_id']]
                for k in ['points','directions','image','weight','source','split']:
                    self.assertEqual(r[k], prior[k])
            else:
                self.assertEqual(r['split'], 'train')
                self.assertTrue(r['frame_id'].startswith('s01e15_'))
                self.assertFalse(220 <= int(r['frame_id'].split('_t')[1][:6]) <= 410)
                self.assertEqual(r['review_status'], 'unreviewed_experimental_only')
                self.assertEqual(r['weight'], .5)
        reference = {r['frame_id'] for r in records if r['split']!='train'}
        self.assertTrue(reference.isdisjoint(groups[2]))
        self.assertEqual(len(reference), 32)
        self.assertTrue(all(r['frame_id'].startswith('s01e24_') for r in records if r['split'] in ['test','challenge_agent_reference']))

    def test_unique_images_and_source_fingerprints(self):
        data = read(OUT/'dataset.json')
        hashes = [sha(ROOT/r['image']) for r in data['records']]
        self.assertEqual(len(hashes), 335)
        self.assertEqual(len(set(hashes)), 335)
        for p, h in data['source_hashes'].items(): self.assertEqual(sha(ROOT/p), h, p)


if __name__ == '__main__': unittest.main()
