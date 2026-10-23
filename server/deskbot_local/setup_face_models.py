"""Explicitly provision checksum-verified OpenCV Zoo face models."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REVISION = "ba91a3b91d00d76e86540d4013f944bd6b514e39"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_recognition_sface_2021dec.onnx": (
        "models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def provision(model_dir: Path = MODEL_DIR) -> None:
    """Download only when this explicit command is run; never replace an existing file."""
    model_dir.mkdir(parents=True, exist_ok=True)
    for filename, (relative_url, expected_hash) in MODELS.items():
        destination = model_dir / filename
        if destination.exists():
            actual_hash = sha256(destination)
            if actual_hash != expected_hash:
                raise ValueError(f"existing model checksum mismatch: {destination}")
            print(f"Verified existing model: {filename}")
            continue
        url = f"https://raw.githubusercontent.com/opencv/opencv_zoo/{REVISION}/{relative_url}"
        fd, temporary_name = tempfile.mkstemp(prefix=f".{filename}-", dir=model_dir)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    digest.update(block)
                    output.write(block)
            if digest.hexdigest() != expected_hash:
                raise ValueError(f"downloaded model checksum mismatch: {filename}")
            os.replace(temporary, destination)
            print(f"Installed checksum-verified model: {destination}")
        except (OSError, urllib.error.URLError, ValueError):
            temporary.unlink(missing_ok=True)
            raise


def main() -> int:
    try:
        provision()
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"Model setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
