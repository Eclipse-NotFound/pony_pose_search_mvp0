"""Synthetic-only checks for end-to-end geometry, losses and scoring."""
import sys
sys.dont_write_bytecode=True
import unittest
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/ai'))
from direction_expanded_train import gaussian_maps, points_from_maps, objective, augment, metric
from direction_pilot import directions_from_points, P_PERM, D_PERM


class ExpandedDirectionTests(unittest.TestCase):
    def fixture(self):
        torch.manual_seed(42)
        p=.25+.5*torch.rand(2,21,2)
        t=dict(p=p,pm=torch.ones(2,21),v=directions_from_points(p),dm=torch.ones(2,14),weight=torch.ones(2))
        # Neural logits are finite; avoid creating -inf from underflowed synthetic tails.
        out=dict(p=p.clone(),v=t['v'].clone(),z=torch.zeros(2,14),hm=gaussian_maps(p).clamp_min(1e-30).log().reshape(2,21,28,28))
        return out,t
    def test_heatmap_decoder_uses_same_coordinate_centers(self):
        out,t=self.fixture()
        self.assertTrue(torch.allclose(points_from_maps(out['hm']),t['p'],atol=1e-4))
    def test_losses_allow_only_whole_leg_reassignment(self):
        out,t=self.fixture();swapped={k:v.clone() for k,v in t.items()}
        for k in ['p','pm']:swapped[k]=t[k][:,P_PERM[3]]
        for k in ['v','dm']:swapped[k]=t[k][:,D_PERM[3]]
        for arm in ['keypoint_heatmap','direct_vector']:
            self.assertAlmostEqual(objective(out,t,arm).item(),objective(out,swapped,arm).item(),places=5)
    def test_augmentation_preserves_point_to_direction_relation(self):
        out,t=self.fixture();x=torch.rand(2,3,224,224)
        _,aug=augment(x,t,np.random.default_rng(3))
        self.assertTrue(torch.allclose(directions_from_points(aug['p']),aug['v'],atol=1e-5))
    def test_unavailable_image_is_not_counted_as_zero_error(self):
        out,t=self.fixture();t['dm'][0]=0;out['v'][1]=-t['v'][1]
        m=metric(out,t)
        self.assertEqual(m['angular_image_count'],1);self.assertIsNone(m['per_image'][0])
        self.assertGreater(m['mae_deg'],90)
    def test_both_losses_produce_finite_gradients(self):
        out,t=self.fixture()
        for arm in ['keypoint_heatmap','direct_vector']:
            pred={k:None if v is None else v.clone().detach().requires_grad_() for k,v in out.items()}
            loss=objective(pred,t,arm);loss.backward()
            self.assertTrue(torch.isfinite(loss))
            self.assertTrue(all(torch.isfinite(v.grad).all() for v in pred.values() if v is not None and v.grad is not None))


if __name__=='__main__':unittest.main()
