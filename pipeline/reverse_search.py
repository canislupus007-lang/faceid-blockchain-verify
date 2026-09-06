"""
Step 2: Genuine Reverse Image Search

Flow:
  1. Compute a perceptual hash (pHash) of the local input image.
  2. Upload the image to a temporary public host (catbox.moe) so Google Lens
     (via SerpApi) can actually fetch and analyze it.
  3. Query SerpApi's Google Lens engine with that public URL.
  4. Parse real "visual matches" results (actual URLs of pages/posts
     containing similar images) -- NOT hardcoded.
  5. For each candidate match with a thumbnail, download the thumbnail and
     compute its pHash, then rank candidates by Hamming distance to our
     input's pHash. This adds a perceptual/content-based signal on top of
     Google's own ranking, and is what gives us resilience to mild crops/
     resizes/compression/filtering.

Requires:
  - SERPAPI_API_KEY in a local .env file (see .env.example)
  - Internet access (uploads image publicly and calls SerpApi)

IMPORTANT LIMITATION:
  Uploading to catbox.moe makes your input image publicly accessible at a
  guessable-if-leaked URL, and unlike some temp hosts, catbox.moe files do
  NOT auto-expire by default -- they persist until manually deleted. This
  is a real privacy tradeoff and should be documented in your README.
  Only use photos you're comfortable being made public indefinitely.
"""

import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import requests
from PIL import Image
import imagehash
from dotenv import load_dotenv
from serpapi import GoogleSearch

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
UPLOAD_ENDPOINT = "https://catbox.moe/user/api.php"


class ReverseSearchError(Exception):
    pass


def compute_phash(image_path: str) -> str:
    """Perceptual hash of a local image file, as a hex string."""
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        return str(imagehash.phash(img))


def compute_phash_from_bytes(content: bytes) -> str:
    from io import BytesIO
    with Image.open(BytesIO(content)) as img:
        img = img.convert("RGB")
        return str(imagehash.phash(img))


def hamming_distance(hash_a: str, hash_b: str) -> int:
    ha = imagehash.hex_to_hash(hash_a)
    hb = imagehash.hex_to_hash(hash_b)
    return int(ha - hb)  # cast from numpy int64 to native int for JSON serialization


def upload_image_publicly(image_path: str) -> str:
    """
    Uploads the image to catbox.moe and returns a public URL.
    Raises ReverseSearchError on failure.

    NOTE: catbox.moe files persist indefinitely (no auto-expiry), unlike
    some other temp hosts. Only use images you're fine being public.
    """
    image_path = Path(image_path)
    with open(image_path, "rb") as f:
        files = {"fileToUpload": (image_path.name, f)}
        data = {"reqtype": "fileupload"}
        resp = requests.post(UPLOAD_ENDPOINT, files=files, data=data, timeout=30)

    if resp.status_code != 200:
        raise ReverseSearchError(
            f"Upload to {UPLOAD_ENDPOINT} failed: HTTP {resp.status_code} - {resp.text[:200]}"
        )

    public_url = resp.text.strip()
    if not public_url.startswith("http"):
        raise ReverseSearchError(f"Unexpected upload response: {public_url}")

    return public_url


def run_google_lens_search(image_url: str) -> dict:
    """
    Calls SerpApi's Google Lens engine on a public image URL.
    Returns the raw JSON response as a dict.
    """
    if not SERPAPI_API_KEY:
        raise ReverseSearchError(
            "SERPAPI_API_KEY not found. Make sure it's set in your .env file."
        )

    params = {
        "engine": "google_lens",
        "url": image_url,
        "api_key": SERPAPI_API_KEY,
    }
    search = GoogleSearch(params)
    results = search.get_dict()

    if "error" in results:
        raise ReverseSearchError(f"SerpApi error: {results['error']}")

    return results


def extract_visual_matches(serpapi_results: dict) -> list:
    """
    Normalizes SerpApi's google_lens response into a flat list of candidate
    matches: [{title, link, source, thumbnail}, ...]
    """
    matches = serpapi_results.get("visual_matches", [])
    normalized = []
    for m in matches:
        normalized.append({
            "title": m.get("title"),
            "link": m.get("link"),
            "source": m.get("source"),
            "thumbnail": m.get("thumbnail"),
        })
    return normalized


def rank_by_perceptual_similarity(matches: list, input_phash: str, max_candidates: int = 10) -> list:
    """
    Downloads thumbnails for up to `max_candidates` matches, computes their
    pHash, and attaches a hamming_distance field. Lower = more visually
    similar. Matches whose thumbnail can't be fetched get hamming_distance
    = None and are sorted last.
    """
    enriched = []
    for m in matches[:max_candidates]:
        entry = dict(m)
        thumb_url = m.get("thumbnail")
        entry["phash"] = None
        entry["hamming_distance"] = None

        if thumb_url:
            try:
                resp = requests.get(thumb_url, timeout=15)
                if resp.status_code == 200:
                    thumb_phash = compute_phash_from_bytes(resp.content)
                    entry["phash"] = thumb_phash
                    entry["hamming_distance"] = hamming_distance(input_phash, thumb_phash)
            except Exception as e:
                entry["thumbnail_fetch_error"] = str(e)

        enriched.append(entry)

    # Sort: matches with a valid hamming_distance first (ascending = more similar),
    # matches with no distance available pushed to the end.
    enriched.sort(key=lambda e: (e["hamming_distance"] is None, e["hamming_distance"] or 0))
    return enriched


def reverse_search(image_path: str) -> dict:
    """
    Full step-2 pipeline. Returns a dict ready to be saved as match_result.json.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Input image not found: {image_path}")

    print(f"[*] Computing perceptual hash of input image...")
    input_phash = compute_phash(image_path)
    print(f"[+] Input pHash: {input_phash}")

    print(f"[*] Uploading image to temporary public host ({UPLOAD_ENDPOINT})...")
    public_url = upload_image_publicly(image_path)
    print(f"[+] Public URL: {public_url}")
    print(f"[!] NOTE: this image is now publicly accessible at that URL until the host expires it.")

    print(f"[*] Querying SerpApi Google Lens...")
    raw_results = run_google_lens_search(public_url)

    matches = extract_visual_matches(raw_results)
    print(f"[+] Google Lens returned {len(matches)} visual match(es).")

    if len(matches) == 0:
        result = {
            "input_image_path": str(image_path),
            "input_phash": input_phash,
            "public_url_used_for_search": public_url,
            "num_matches_found": 0,
            "matches": [],
            "best_match": None,
            "engine": "serpapi/google_lens",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        return result

    print(f"[*] Ranking matches by perceptual similarity...")
    ranked_matches = rank_by_perceptual_similarity(matches, input_phash)
    best_match = ranked_matches[0] if ranked_matches else None

    result = {
        "input_image_path": str(image_path),
        "input_phash": input_phash,
        "public_url_used_for_search": public_url,
        "num_matches_found": len(ranked_matches),
        "matches": ranked_matches,
        "best_match": best_match,
        "engine": "serpapi/google_lens",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return result


def save_match_result(result: dict, output_path: str = "outputs/match_result.json"):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reverse_search.py <path_to_image> [output_json_path]")
        sys.exit(1)

    image_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "outputs/match_result.json"

    try:
        result = reverse_search(image_path)
    except (ReverseSearchError, FileNotFoundError) as e:
        print(f"[!] {e}")
        sys.exit(2)

    saved_path = save_match_result(result, output_path)

    print()
    if result["num_matches_found"] == 0:
        print("[!] No public matches found for this image.")
    else:
        best = result["best_match"]
        print(f"[+] Best match: {best.get('title')}")
        print(f"[+] Source URL: {best.get('link')}")
        print(f"[+] Hamming distance (lower=more similar): {best.get('hamming_distance')}")

    print(f"[+] Full results saved to: {saved_path}")
