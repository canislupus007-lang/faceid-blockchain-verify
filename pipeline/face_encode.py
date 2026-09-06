"""
Step 1: Face Detection + Encoding

Uses InsightFace (buffalo_l model pack) to detect a face in an input image
and produce a 512-dimensional embedding vector.

On first run, InsightFace will automatically download the buffalo_l model
pack (~300MB) to ~/.insightface/models/. This requires internet access
and only happens once.
"""

import json
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone

import cv2
import numpy as np
from insightface.app import FaceAnalysis


class FaceEncodingError(Exception):
    """Raised when no face (or an ambiguous number of faces) is found."""
    pass


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_face_app(det_size=(640, 640), ctx_id: int = -1) -> FaceAnalysis:
    """
    Initialize the InsightFace app.
    ctx_id = -1 forces CPU. Use ctx_id = 0 if you have a CUDA GPU set up.
    """
    app = FaceAnalysis(name="buffalo_l")
    app.prepare(ctx_id=ctx_id, det_size=det_size)
    return app


def encode_face(image_path: str, app: FaceAnalysis = None) -> dict:
    """
    Detect the largest/primary face in the image and return its encoding
    plus metadata as a dict. Raises FaceEncodingError if no face is found.

    If multiple faces are detected, the largest bounding box is used as the
    primary subject, and the count of other detected faces is recorded.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Input image not found: {image_path}")

    if app is None:
        app = load_face_app()

    img_bgr = cv2.imread(str(image_path))
    if img_bgr is None:
        raise ValueError(f"Could not read image (unsupported format?): {image_path}")

    faces = app.get(img_bgr)

    if len(faces) == 0:
        raise FaceEncodingError(f"No face detected in {image_path}")

    # Pick the largest face by bounding box area as the primary subject.
    def bbox_area(face):
        x1, y1, x2, y2 = face.bbox
        return (x2 - x1) * (y2 - y1)

    faces_sorted = sorted(faces, key=bbox_area, reverse=True)
    primary = faces_sorted[0]

    embedding = primary.normed_embedding.astype(np.float64).tolist()
    embedding_hash = hashlib.sha256(
        json.dumps(embedding).encode("utf-8")
    ).hexdigest()

    result = {
        "input_image_path": str(image_path),
        "input_image_sha256": _sha256_of_file(image_path),
        "num_faces_detected": len(faces),
        "primary_face": {
            "bbox": [float(x) for x in primary.bbox],
            "detection_score": float(primary.det_score),
            "embedding_dim": len(embedding),
            "embedding": embedding,
            "embedding_sha256": embedding_hash,
        },
        "model": "insightface/buffalo_l",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return result


def save_encoding(result: dict, output_path: str = "outputs/face_embedding.json"):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python face_encode.py <path_to_image> [output_json_path]")
        sys.exit(1)

    image_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "outputs/face_embedding.json"

    print(f"[*] Loading InsightFace (buffalo_l)...")
    app = load_face_app()

    print(f"[*] Encoding face from: {image_path}")
    try:
        result = encode_face(image_path, app=app)
    except FaceEncodingError as e:
        print(f"[!] {e}")
        sys.exit(2)

    saved_path = save_encoding(result, output_path)
    print(f"[+] Detected {result['num_faces_detected']} face(s).")
    print(f"[+] Primary face detection score: {result['primary_face']['detection_score']:.4f}")
    print(f"[+] Embedding ({result['primary_face']['embedding_dim']}-d) saved to: {saved_path}")
    print(f"[+] Embedding SHA-256: {result['primary_face']['embedding_sha256']}")
