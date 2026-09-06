"""
End-to-end pipeline orchestrator.

Runs all three steps in order on a single input image:
  1. Face detection + encoding
  2. Genuine reverse image search
  3. Blockchain notarization

Usage:
    python pipeline/run_pipeline.py samples/your_photo.jpg
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from face_encode import load_face_app, encode_face, save_encoding, FaceEncodingError
from reverse_search import reverse_search, save_match_result, ReverseSearchError
from blockchain_notarize import (
    build_evidence_record,
    hash_record,
    notarize_hash,
    save_receipt,
    NotarizationError,
)


def run_full_pipeline(image_path: str, output_dir: str = "outputs"):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("STEP 1: Face Detection + Encoding")
    print("=" * 60)
    app = load_face_app()
    try:
        face_result = encode_face(image_path, app=app)
    except FaceEncodingError as e:
        print(f"[!] {e}")
        sys.exit(2)
    face_path = save_encoding(face_result, output_dir / "face_embedding.json")
    print(f"[+] Detected {face_result['num_faces_detected']} face(s), "
          f"score {face_result['primary_face']['detection_score']:.4f}")
    print(f"[+] Saved to {face_path}\n")

    print("=" * 60)
    print("STEP 2: Genuine Reverse Image Search")
    print("=" * 60)
    try:
        match_result = reverse_search(image_path)
    except (ReverseSearchError, FileNotFoundError) as e:
        print(f"[!] {e}")
        sys.exit(2)
    match_path = save_match_result(match_result, output_dir / "match_result.json")
    print(f"[+] Found {match_result['num_matches_found']} match(es)")
    if match_result["best_match"]:
        print(f"[+] Best match: {match_result['best_match'].get('link')}")
    print(f"[+] Saved to {match_path}\n")

    print("=" * 60)
    print("STEP 3: Blockchain Notarization")
    print("=" * 60)
    try:
        record = build_evidence_record(face_path, match_path)
        record_hash = hash_record(record)
        print(f"[+] Evidence record SHA-256: {record_hash}")
        receipt = notarize_hash(record_hash)
    except (NotarizationError, FileNotFoundError) as e:
        print(f"[!] {e}")
        sys.exit(2)
    receipt_path = save_receipt(receipt, record, output_dir / "tx_receipt.json")
    print(f"[+] Confirmed in block {receipt['block_number']}")
    print(f"[+] Etherscan: {receipt['explorer_url']}")
    print(f"[+] Saved to {receipt_path}\n")

    print("=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Face embedding: {face_path}")
    print(f"Match result:   {match_path}")
    print(f"Tx receipt:     {receipt_path}")
    print(f"Verify anytime with: python verify.py {receipt_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline/run_pipeline.py <path_to_image> [output_dir]")
        sys.exit(1)

    image_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "outputs"
    run_full_pipeline(image_path, output_dir)
