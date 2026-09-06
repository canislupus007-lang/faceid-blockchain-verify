"""
Cropping / resize / compression robustness demo.

Takes a real input image, creates 3 degraded versions of it (cropped,
resized+compressed, and both combined), computes perceptual hashes for
all of them, and shows the Hamming distance to the original -- proving
the pipeline's perceptual-matching approach tolerates these edits far
better than exact pixel/file hashing would.

Optionally (if you pass --live-search), it also re-runs the actual
Step 2 reverse image search on the cropped version to show Google Lens
still finds a genuine match.

Usage:
    python robustness_demo.py samples/your_photo.jpg
    python robustness_demo.py samples/your_photo.jpg --live-search
"""

import sys
import hashlib
from pathlib import Path
from PIL import Image
import imagehash

sys.path.insert(0, str(Path(__file__).parent / "pipeline"))
from reverse_search import compute_phash, hamming_distance, reverse_search


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_degraded_versions(image_path: str, out_dir: str = "outputs/robustness_demo"):
    image_path = Path(image_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    versions = {}

    # 1. Light crop (5% off each edge)
    cropped = img.crop((int(w * 0.05), int(h * 0.05), int(w * 0.95), int(h * 0.95)))
    crop_path = out_dir / "cropped.jpg"
    cropped.save(crop_path, quality=90)
    versions["Lightly cropped (5% each edge)"] = crop_path

    # 2. Resized + heavily compressed
    resized = img.resize((int(w * 0.6), int(h * 0.6)))
    resize_path = out_dir / "resized_compressed.jpg"
    resized.save(resize_path, quality=40)
    versions["Resized 60% + compressed (quality=40)"] = resize_path

    # 3. Both combined (worst case)
    combo = img.crop((int(w * 0.08), int(h * 0.08), int(w * 0.92), int(h * 0.92)))
    combo = combo.resize((int(combo.width * 0.7), int(combo.height * 0.7)))
    combo_path = out_dir / "cropped_and_resized.jpg"
    combo.save(combo_path, quality=50)
    versions["Cropped + resized + compressed"] = combo_path

    return versions


def run_demo(image_path: str, live_search: bool = False):
    original_phash = compute_phash(image_path)
    with open(image_path, "rb") as f:
        original_sha256 = sha256_of_bytes(f.read())

    print("=" * 70)
    print("ORIGINAL IMAGE")
    print("=" * 70)
    print(f"SHA-256 (exact file hash): {original_sha256}")
    print(f"pHash (perceptual hash):   {original_phash}")
    print()

    versions = make_degraded_versions(image_path)

    print("=" * 70)
    print("DEGRADED VERSIONS -- exact hash vs perceptual hash comparison")
    print("=" * 70)
    print(f"{'Version':<40} {'Exact match?':<14} {'Hamming dist':<14}")
    print("-" * 70)

    for label, path in versions.items():
        with open(path, "rb") as f:
            file_bytes = f.read()
        version_sha256 = sha256_of_bytes(file_bytes)
        version_phash = compute_phash(path)
        dist = hamming_distance(original_phash, version_phash)
        exact_match = "YES" if version_sha256 == original_sha256 else "NO"
        print(f"{label:<40} {exact_match:<14} {dist:<14}")

    print()
    print("Interpretation: SHA-256 (exact hash) always says 'NO' for any")
    print("edited image, even a single re-saved JPEG -- it is useless for")
    print("detecting near-duplicates. Perceptual hash (pHash) Hamming")
    print("distance stays LOW (typically <15 out of 64 bits) for genuinely")
    print("similar images, which is what lets this pipeline recognize an")
    print("edited repost of the same photo.")
    print()

    if live_search:
        print("=" * 70)
        print("LIVE TEST: re-running reverse image search on cropped version")
        print("=" * 70)
        cropped_path = versions["Lightly cropped (5% each edge)"]
        try:
            result = reverse_search(str(cropped_path))
            print(f"Matches found on cropped image: {result['num_matches_found']}")
            if result["best_match"]:
                print(f"Best match: {result['best_match'].get('link')}")
                print(f"Hamming distance: {result['best_match'].get('hamming_distance')}")
        except Exception as e:
            print(f"[!] Live search failed: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python robustness_demo.py <path_to_image> [--live-search]")
        sys.exit(1)

    image_path = sys.argv[1]
    live_search = "--live-search" in sys.argv
    run_demo(image_path, live_search=live_search)
