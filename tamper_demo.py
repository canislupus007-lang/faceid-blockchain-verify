"""
Tamper-detection demo.

Takes a real, already-notarized tx_receipt.json and creates a deliberately
tampered copy (by altering one field in the evidence record, e.g. the
matched URL), WITHOUT re-notarizing it. Then runs the same verification
logic used by verify.py against this tampered copy.

This demonstrates, live, that any post-hoc edit to the evidence record
is detected: the on-chain hash was computed from the ORIGINAL record, so
a tampered record will no longer hash to the same value.

Usage:
    python tamper_demo.py outputs/tx_receipt.json
"""

import sys
import json
import hashlib
import copy
from pathlib import Path


def demo_tamper_detection(receipt_path: str):
    receipt_path = Path(receipt_path)
    with open(receipt_path) as f:
        original = json.load(f)

    print("=" * 60)
    print("ORIGINAL (untampered) evidence record")
    print("=" * 60)
    print(json.dumps(original["evidence_record"], indent=2))

    onchain_hash = original["blockchain_receipt"]["record_hash_sha256"]
    print(f"\nHash notarized on-chain: {onchain_hash}")

    # Recompute hash of the original record to prove it matches on-chain value
    original_record_canonical = json.dumps(original["evidence_record"], sort_keys=True)
    original_hash = hashlib.sha256(original_record_canonical.encode("utf-8")).hexdigest()
    print(f"Recomputed hash (original): {original_hash}")
    print(f"Match: {original_hash == onchain_hash}\n")

    # Now create a tampered copy: attacker changes the matched URL to
    # point somewhere else, hoping to pass off a fake finding.
    tampered = copy.deepcopy(original)
    fake_url = "https://totally-legit-not-fake-site.example/fabricated-match"
    print("=" * 60)
    print(f"SIMULATING TAMPERING: changing best_match_url to:")
    print(f"  {fake_url}")
    print("=" * 60)
    tampered["evidence_record"]["best_match_url"] = fake_url

    tampered_record_canonical = json.dumps(tampered["evidence_record"], sort_keys=True)
    tampered_hash = hashlib.sha256(tampered_record_canonical.encode("utf-8")).hexdigest()

    print(f"\nHash of TAMPERED record: {tampered_hash}")
    print(f"Hash actually on-chain:  {onchain_hash}")
    print()

    if tampered_hash != onchain_hash:
        print("[+] TAMPERING DETECTED.")
        print("[+] The tampered record's hash does NOT match what was")
        print("[+] notarized on-chain. Anyone re-running verify.py against")
        print("[+] this tampered file would see a MISMATCH and know the")
        print("[+] record has been altered since it was originally notarized.")
    else:
        print("[!] Unexpected: hashes matched. This should not happen.")

    # Save the tampered file so the user can immediately demo it against
    # the real verify.py script for the video.
    tampered_path = receipt_path.parent / "tx_receipt_TAMPERED_DEMO.json"
    with open(tampered_path, "w") as f:
        json.dump(tampered, f, indent=2)
    print(f"\n[+] Tampered demo file saved to: {tampered_path}")
    print(f"[+] Try it yourself: python verify.py {tampered_path}")
    print(f"[+] (It will print a MISMATCH, unlike the original which prints VERIFIED)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tamper_demo.py <path_to_tx_receipt.json>")
        sys.exit(1)
    demo_tamper_detection(sys.argv[1])
