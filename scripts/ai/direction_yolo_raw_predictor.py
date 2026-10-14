"""Preserve low-confidence coordinates for fair, reference-masked scoring.

Ultralytics 8.3.75 Keypoints sets xy to zero below confidence 0.5, including
in .data. This local predictor retains the pre-display-filter coordinates;
it changes neither the network nor the detection/NMS/coordinate transforms.
"""
import sys
sys.dont_write_bytecode=True
from ultralytics.models.yolo.pose.predict import PosePredictor
from ultralytics.utils import ops


class RawPosePredictor(PosePredictor):
    def construct_result(self,pred,img,orig_img,img_path):
        raw=pred[:,6:].clone()
        result=super().construct_result(pred,img,orig_img,img_path)
        if len(pred):
            raw=raw.view(len(pred),*self.model.kpt_shape)
            result.keypoints.data=ops.scale_coords(img.shape[2:],raw,orig_img.shape)
        return result
