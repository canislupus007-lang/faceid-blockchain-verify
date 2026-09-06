"""
Standalone re-verification script.

Given a tx_receipt.json file (produced by blockchain_notarize.py), this
script:
  1. Re-fetches the transaction from Sepolia using its tx hash.
  2. Extracts the hash embedded in the transaction's data field.
  3. Recomputes the SHA-256 of the stored evidence_record.
  4. Compares the two. If they match, the record has NOT been tampered
     with since it was notarized -- this is the "tamper-evident,
     re-verifiable" guarantee.

This can be run by anyone, at any time, using only a copy of
tx_receipt.json and public Sepolia infrastructure -- no access to your
wallet, API keys, or original photo is required for someone else to
verify the record's integrity.

Usage:
    python verify.py outputs/tx_receipt.json
"""

import os
import sys
import json
from pathlib import Path

from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL", "https://rpc.sepolia.org")


def verify_receipt(receipt_path: str) -> bool:
    receipt_path = Path(receipt_path)
    if not receipt_path.exists():
        print(f"[!] Receipt file not found: {receipt_path}")
        return False

    with open(receipt_path) as f:
        data = json.load(f)

    evidence_record = data["evidence_record"]
    blockchain_receipt = data["blockchain_receipt"]
    tx_hash = blockchain_receipt["tx_hash"]
    claimed_record_hash = blockchain_receipt["record_hash_sha256"]

    print(f"[*] Connecting to Sepolia via {SEPOLIA_RPC_URL} ...")
    w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
    if not w3.is_connected():
        print(f"[!] Could not connect to RPC endpoint: {SEPOLIA_RPC_URL}")
        return False

    print(f"[*] Fetching transaction {tx_hash} from chain...")
    try:
        tx = w3.eth.get_transaction(tx_hash)
    except Exception as e:
        print(f"[!] Could not fetch transaction: {e}")
        return False

    raw_data = tx["input"]
    if isinstance(raw_data, (bytes, bytearray)):
        decoded = raw_data.decode("utf-8", errors="replace")
    else:
        # some web3 versions return a HexBytes-like object; normalize
        decoded = bytes(raw_data).decode("utf-8", errors="replace")

    prefix = "faceid-blockchain-verify:"
    if not decoded.startswith(prefix):
        print(f"[!] Unexpected data format in transaction: {decoded[:60]}")
        return False

    onchain_hash = decoded[len(prefix):]

    # Recompute the hash of the stored evidence record the same way
    # blockchain_notarize.py did.
    import hashlib
    canonical = json.dumps(evidence_record, sort_keys=True)
    recomputed_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    print()
    print(f"Hash recorded on-chain:      {onchain_hash}")
    print(f"Hash recomputed from record: {recomputed_hash}")
    print(f"Hash stored in receipt file: {claimed_record_hash}")
    print()

    match = (onchain_hash == recomputed_hash == claimed_record_hash)
    if match:
        print("[+] VERIFIED: record integrity confirmed. No tampering detected.")
    else:
        print("[!] MISMATCH: the record does not match what was notarized on-chain.")
        print("[!] This means either the evidence_record was altered after the")
        print("[!] fact, or this receipt does not correspond to the given tx_hash.")

    return match


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify.py <path_to_tx_receipt.json>")
        sys.exit(1)

    ok = verify_receipt(sys.argv[1])
    sys.exit(0 if ok else 1)
