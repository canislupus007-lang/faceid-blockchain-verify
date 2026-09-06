"""
IPFS evidence storage via Pinata.

Uploads the full evidence bundle (face embedding metadata + match result +
evidence record -- everything except the raw face embedding vector, which
is never published) as a single JSON file to IPFS via Pinata's free tier.
Returns a CID (content identifier) that anyone can use to fetch the full
evidence bundle from any IPFS gateway, forever (as long as it stays
pinned).

This is combined with on-chain notarization: instead of putting ONLY a
hash on-chain, we put the hash AND the IPFS CID, so a verifier can:
  1. Read the CID from the blockchain transaction
  2. Fetch the full evidence bundle from IPFS using that CID
  3. Recompute its hash and compare against the on-chain hash

This gives you decentralized storage (IPFS) + decentralized integrity
proof (blockchain) working together, rather than only a bare hash.

Requires (in .env):
  PINATA_JWT  -- get a free one at https://app.pinata.cloud (Developers -> API Keys)
"""

import os
import sys
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

PINATA_JWT = os.getenv("PINATA_JWT")
PINATA_UPLOAD_URL = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
IPFS_GATEWAY = "https://gateway.pinata.cloud/ipfs"


class IPFSUploadError(Exception):
    pass


def build_evidence_bundle(face_embedding_path: str, match_result_path: str) -> dict:
    """
    Combines Step 1 + Step 2 outputs into a full evidence bundle for IPFS.
    Unlike the on-chain record, this can include more detail (e.g. all
    matches, not just the best one) since IPFS storage is cheap and this
    isn't going directly into a transaction's data field.

    The raw 512-d face embedding vector is still excluded -- only its
    hash -- since it's sensitive biometric data.
    """
    with open(face_embedding_path) as f:
        face_data = json.load(f)
    with open(match_result_path) as f:
        match_data = json.load(f)

    bundle = {
        "input_image_sha256": face_data.get("input_image_sha256"),
        "face_detection": {
            "num_faces_detected": face_data.get("num_faces_detected"),
            "detection_score": face_data["primary_face"]["detection_score"],
            "embedding_sha256": face_data["primary_face"]["embedding_sha256"],
            "model": face_data.get("model"),
        },
        "reverse_search": {
            "input_phash": match_data.get("input_phash"),
            "num_matches_found": match_data.get("num_matches_found"),
            "matches": match_data.get("matches", []),
            "engine": match_data.get("engine"),
        },
        "pipeline": "faceid-blockchain-verify",
    }
    return bundle


def upload_to_ipfs(bundle: dict, name: str = "faceid-evidence-bundle") -> str:
    """
    Uploads a JSON-serializable dict to IPFS via Pinata. Returns the CID.
    """
    if not PINATA_JWT:
        raise IPFSUploadError(
            "PINATA_JWT not set in .env. Get a free one at https://app.pinata.cloud"
        )

    headers = {
        "Authorization": f"Bearer {PINATA_JWT}",
        "Content-Type": "application/json",
    }
    payload = {
        "pinataMetadata": {"name": name},
        "pinataContent": bundle,
    }

    resp = requests.post(PINATA_UPLOAD_URL, json=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise IPFSUploadError(f"Pinata upload failed: HTTP {resp.status_code} - {resp.text[:300]}")

    data = resp.json()
    cid = data.get("IpfsHash")
    if not cid:
        raise IPFSUploadError(f"Unexpected Pinata response: {data}")

    return cid


def fetch_from_ipfs(cid: str) -> dict:
    """
    Fetches and parses a JSON evidence bundle back from IPFS by CID.
    Used by re-verifiers who only have a CID (e.g. read from a blockchain
    record) and want to pull the full bundle.
    """
    url = f"{IPFS_GATEWAY}/{cid}"
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        raise IPFSUploadError(f"Could not fetch {url}: HTTP {resp.status_code}")
    return resp.json()


if __name__ == "__main__":
    face_embedding_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/face_embedding.json"
    match_result_path = sys.argv[2] if len(sys.argv) > 2 else "outputs/match_result.json"

    print("[*] Building evidence bundle...")
    bundle = build_evidence_bundle(face_embedding_path, match_result_path)

    print("[*] Uploading to IPFS via Pinata...")
    try:
        cid = upload_to_ipfs(bundle)
    except IPFSUploadError as e:
        print(f"[!] {e}")
        sys.exit(2)

    gateway_url = f"{IPFS_GATEWAY}/{cid}"
    print(f"[+] Uploaded. CID: {cid}")
    print(f"[+] View at: {gateway_url}")

    out_path = Path("outputs/ipfs_upload.json")
    with open(out_path, "w") as f:
        json.dump({"cid": cid, "gateway_url": gateway_url, "bundle": bundle}, f, indent=2)
    print(f"[+] Saved to: {out_path}")
