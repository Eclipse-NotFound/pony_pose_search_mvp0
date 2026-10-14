"""Use saved pilot checkpoints, or verify all saved predictions from raw images.

Outputs are experimental directions, not approved annotations. No production
model, annotation, or search index is modified. No download occurs in this file.
"""
import sys
sys.dont_write_bytecode = True
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from torch import nn
from torchvision.models import resnet18
from direction_pilot import Head, prepare_record
from direction_pilot_data import ROOT, OUT, NAMES, read, write, sha


def load_encoder():
    path = OUT / "weights/hub/checkpoints/resnet18-f37072fd.pth"
    expected = read(OUT / "summary.json")["environment"]["encoder_weights_sha256"]
    if sha(path) != expected:
        raise ValueError("Encoder weights differ from the recorded experiment")
    base = resnet18(weights=None)
    base.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
    return nn.Sequential(*list(base.children())[:-2],
                         nn.AdaptiveAvgPool2d((2, 2)), nn.Flatten()).eval()


def features(records):
    encoder = load_encoder()
    scale = torch.load(OUT / "feature_scale.pt", map_location="cpu", weights_only=True)
    images = torch.stack([prepare_record(r)[0] for r in records])
    with torch.inference_mode():
        return (encoder(images) - scale["mean"]) / scale["std"]


def predict(checkpoint, x):
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model = Head(saved["input_dim"], saved["arm"])
    model.load_state_dict(saved["state_dict"])
    model.eval()
    with torch.inference_mode():
        _, vectors, logits = model(x)
    return saved, vectors.numpy(), logits.sigmoid().numpy()


def verify_experiment():
    dataset = read(OUT / "dataset.json")
    summary = read(OUT / "summary.json")
    for name in ["dataset", "protocol"]:
        assert sha(OUT / f"{name}.json") == summary["environment"][f"{name}_sha256"]
    for path, expected in dataset["source_hashes"].items():
        assert sha(ROOT / path) == expected, path
    records = [r for r in dataset["records"] if r["split"] == "test"]
    x = features(records)
    checks = []
    for folder in sorted((OUT / "runs").iterdir()):
        result = read(folder / "result.json")
        assert result["test_frame_ids"] == [r["frame_id"] for r in records]
        _, vectors, availability = predict(folder / "head.pt", x)
        error = float(np.max(np.abs(vectors - np.array(result["test_vectors"])) ))
        availability_error = float(np.max(np.abs(availability - np.array(result["test_availability"])) ))
        assert np.isfinite(vectors).all() and np.isfinite(availability).all()
        assert error < 2e-4 and availability_error < 2e-4, (folder.name, error, availability_error)
        checks.append(dict(run=folder.name, max_vector_difference=error,
                           max_availability_difference=availability_error,
                           checkpoint_sha256=sha(folder / "head.pt")))
    assert len(checks) == 18
    report = dict(status="passed", method="Reload encoder, scaler and each head; recompute from all 12 original test images; compare against saved predictions", source_files_unchanged=len(dataset["source_hashes"]), checkpoints=checks,
                  feature_scale_sha256=sha(OUT / "feature_scale.pt"))
    write(OUT / "reload_verification.json", report)
    print(f"Passed: {len(checks)} checkpoints, {len(records)} images each, {len(dataset['source_hashes'])} unchanged source files")
    print(f"Maximum vector difference: {max(c['max_vector_difference'] for c in checks):.8g}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-experiment", action="store_true")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.verify_experiment:
        verify_experiment()
        return
    if args.checkpoint is None or args.image is None or args.output is None:
        parser.error("prediction requires --checkpoint, --image and --output")
    output = args.output.resolve()
    if not output.is_relative_to(OUT.resolve()):
        parser.error("experimental outputs must stay inside the experiment directory")
    if output.exists():
        parser.error("refusing to overwrite an existing output")
    path = args.image.resolve()
    with Image.open(path) as image:
        size = list(image.size)
    record = dict(image=str(path), size=size, points=[None] * 21)
    saved, vectors, availability = predict(args.checkpoint, features([record]))
    write(output, dict(status="unreviewed_experimental_prediction", image=str(path),
                       arm=saved["arm"], regime=saved["regime"], seed=saved["seed"],
                       axes="x right, y down; 2D unit directions; no predicted anchors",
                       availability_note="Uncalibrated model scores, not human approval",
                       directions={name: dict(vector=v.tolist(), availability_score=float(c))
                                   for name, v, c in zip(NAMES, vectors[0], availability[0])}))
    print(output)


if __name__ == "__main__":
    main()
