"""Explicit one-time model download; normal preview is entirely offline."""

import os
import hashlib
import tempfile
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile, BadZipFile

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
DEFAULT_MODEL = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"
MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"


def download_model(destination: Path = DEFAULT_MODEL) -> Path:
    if destination.is_file():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError(f"Existing model does not match the official pinned bundle: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=destination.parent, suffix=".download")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream, urlopen(MODEL_URL, timeout=30) as response:
            total = 0
            while chunk := response.read(65536):
                total += len(chunk)
                if total > 32 * 1024 * 1024:
                    raise ValueError("Model response exceeds expected size")
                stream.write(chunk)
        try:
            with ZipFile(temporary) as bundle:
                if not {"hand_detector.tflite", "hand_landmarks_detector.tflite"} <= set(bundle.namelist()):
                    raise ValueError("Downloaded file is not a Hand Landmarker bundle")
                if bundle.testzip() is not None:
                    raise ValueError("Corrupted model bundle")
        except BadZipFile as exc:
            raise ValueError("Invalid model download") from exc
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError("Model checksum does not match pinned version")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
