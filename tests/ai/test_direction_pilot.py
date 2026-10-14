"""Synthetic geometry and evaluation checks; no personal samples are test inputs."""
import sys
sys.dont_write_bytecode=True
import unittest
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts/ai"))
from direction_pilot import directions_from_points, align_metrics, objective, Head, P_PERM, D_PERM

class DirectionPilotTests(unittest.TestCase):
    def targets(self):
        p=torch.stack([torch.tensor([i*.02,i*.01]) for i in range(21)])[None]
        return dict(p=p,pm=torch.ones(1,21),v=directions_from_points(p),dm=torch.ones(1,14),weight=torch.ones(1))
    def test_translation_and_uniform_scale_do_not_change_direction(self):
        t=self.targets();self.assertTrue(torch.allclose(directions_from_points(t['p']*2.3+torch.tensor([.1,-.3])),t['v'],atol=1e-5))
    def test_flip_reverses_x_only(self):
        t=self.targets();p=t['p'].clone();p[:,:,0]=1-p[:,:,0];expected=t['v'].clone();expected[:,:,0]*=-1
        self.assertTrue(torch.allclose(directions_from_points(p),expected,atol=1e-5))
    def test_whole_leg_permutations_preserve_segment_order(self):
        self.assertEqual(D_PERM[3].tolist(),[0,1,2,3,6,7,4,5,11,12,13,8,9,10])
        self.assertEqual(P_PERM[1][5:11].tolist(),[8,9,10,5,6,7])
    def test_missing_truth_not_counted_and_bad_confidence_cannot_hide_error(self):
        t=self.targets();t['dm'][:]=0;t['dm'][0,0]=1
        v=t['v'].clone();v[:,0]*=-1
        m=align_metrics(v,torch.full((1,14),-20.),t)
        self.assertAlmostEqual(m['mae_deg'],180,places=2)
    def test_zero_prediction_scores_as_failure(self):
        t=self.targets();m=align_metrics(torch.zeros(1,14,2),torch.zeros(1,14),t)
        self.assertEqual(m['mae_deg'],180)
    def test_all_objectives_have_finite_gradients(self):
        for arm in ['keypoint','keypoint_angle','direct']:
            net=Head(10,arm);loss=objective(net(torch.randn(1,10)),self.targets(),arm);loss.backward()
            self.assertTrue(torch.isfinite(loss));self.assertTrue(all(torch.isfinite(p.grad).all() for p in net.parameters()))

if __name__=='__main__':unittest.main()
