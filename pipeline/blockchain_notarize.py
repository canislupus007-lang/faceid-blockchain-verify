"""
Step 3: Blockchain Notarization

Takes the outputs from Step 1 (face_embedding.json) and Step 2
(match_result.json), builds a combined evidence record, hashes it with
SHA-256, and writes that hash into a real Sepolia testnet transaction's
data field. No smart contract is needed -- the transaction itself,
once mined, is a permanent, publicly re-verifiable, tamper-evident
record: anyone can look up the tx hash on Etherscan, read the data
field back out, and confirm it matches a recomputed hash of the
original evidence record.

Requires (in .env):
  - SEPOLIA_RPC_URL   (e.g. https://rpc.sepolia.org)
  - WALLET_PRIVATE_KEY (your MetaMask private key, Sepolia testnet only)
"""

import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

SEPOLIA_RPC_URL = os.getenv("SEPOLIA_RPC_URL")
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")


class NotarizationError(Exception):
    pass


def build_evidence_record(face_embedding_path: str, match_result_path: str) -> dict:
    """
    Combines the outputs of Step 1 and Step 2 into a single evidence
    record. We deliberately exclude the raw 512-d face embedding vector
    itself from what gets hashed/published -- only its hash is included,
    so no biometric data is exposed on a public, permanent ledger.
    """
    face_embedding_path = Path(face_embedding_path)
    match_result_path = Path(match_result_path)

    if not face_embedding_path.exists():
        raise FileNotFoundError(f"Missing Step 1 output: {face_embedding_path}")
    if not match_result_path.exists():
        raise FileNotFoundError(f"Missing Step 2 output: {match_result_path}")

    with open(face_embedding_path) as f:
        face_data = json.load(f)
    with open(match_result_path) as f:
        match_data = json.load(f)

    best_match = match_data.get("best_match") or {}

    record = {
        "input_image_sha256": face_data.get("input_image_sha256"),
        "face_embedding_sha256": face_data["primary_face"]["embedding_sha256"],
        "face_detection_score": face_data["primary_face"]["detection_score"],
        "input_phash": match_data.get("input_phash"),
        "num_matches_found": match_data.get("num_matches_found"),
        "best_match_url": best_match.get("link"),
        "best_match_title": best_match.get("title"),
        "best_match_hamming_distance": best_match.get("hamming_distance"),
        "search_engine": match_data.get("engine"),
        "record_generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return record


def hash_record(record: dict) -> str:
    """
    Deterministic SHA-256 hash of the evidence record. sort_keys=True
    ensures the same record always hashes the same way regardless of
    dict ordering, which matters for re-verification later.
    """
    canonical = json.dumps(record, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def connect_web3() -> Web3:
    if not SEPOLIA_RPC_URL:
        raise NotarizationError("SEPOLIA_RPC_URL not set in .env")
    w3 = Web3(Web3.HTTPProvider(SEPOLIA_RPC_URL))
    if not w3.is_connected():
        raise NotarizationError(f"Could not connect to RPC endpoint: {SEPOLIA_RPC_URL}")
    return w3


def notarize_hash(record_hash: str) -> dict:
    """
    Sends a Sepolia transaction to yourself (0 ETH value) with the
    record hash embedded in the data field. Returns transaction details
    including the tx hash and Etherscan link.
    """
    if not WALLET_PRIVATE_KEY:
        raise NotarizationError("WALLET_PRIVATE_KEY not set in .env")

    w3 = connect_web3()
    account = w3.eth.account.from_key(WALLET_PRIVATE_KEY)
    sender_address = account.address

    balance = w3.eth.get_balance(sender_address)
    if balance == 0:
        raise NotarizationError(
            f"Wallet {sender_address} has 0 Sepolia ETH. Fund it via a faucet first."
        )

    # Prefix the hash with a marker so it's human-recognizable when
    # someone inspects the raw tx data on Etherscan later.
    data_payload = f"faceid-blockchain-verify:{record_hash}".encode("utf-8")

    nonce = w3.eth.get_transaction_count(sender_address)
    gas_price = w3.eth.gas_price

    tx = {
        "nonce": nonce,
        "to": sender_address,   # send to self -- we only care about the data field
        "value": 0,
        "gas": 100000,
        "gasPrice": gas_price,
        "data": data_payload,
        "chainId": w3.eth.chain_id,
    }

    signed_tx = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    tx_hash_hex = tx_hash.hex()

    print(f"[*] Transaction sent: {tx_hash_hex}")
    print(f"[*] Waiting for confirmation (this can take 15-60 seconds)...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash_hex, timeout=180)

    explorer_url = f"https://sepolia.etherscan.io/tx/{tx_hash_hex}"

    return {
        "tx_hash": tx_hash_hex,
        "block_number": receipt["blockNumber"],
        "sender_address": sender_address,
        "chain": "sepolia",
        "chain_id": w3.eth.chain_id,
        "explorer_url": explorer_url,
        "record_hash_sha256": record_hash,
        "confirmed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def save_receipt(receipt: dict, evidence_record: dict, output_path: str = "outputs/tx_receipt.json"):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    full_output = {
        "evidence_record": evidence_record,
        "blockchain_receipt": receipt,
    }
    with open(output_path, "w") as f:
        json.dump(full_output, f, indent=2)
    return output_path


if __name__ == "__main__":
    face_embedding_path = sys.argv[1] if len(sys.argv) > 1 else "outputs/face_embedding.json"
    match_result_path = sys.argv[2] if len(sys.argv) > 2 else "outputs/match_result.json"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "outputs/tx_receipt.json"

    try:
        print("[*] Building evidence record from Step 1 + Step 2 outputs...")
        record = build_evidence_record(face_embedding_path, match_result_path)
        record_hash = hash_record(record)
        print(f"[+] Evidence record SHA-256: {record_hash}")

        print("[*] Submitting to Sepolia testnet...")
        receipt = notarize_hash(record_hash)

    except (NotarizationError, FileNotFoundError) as e:
        print(f"[!] {e}")
        sys.exit(2)

    saved_path = save_receipt(receipt, record, output_path)

    print()
    print(f"[+] Confirmed in block: {receipt['block_number']}")
    print(f"[+] Transaction hash: {receipt['tx_hash']}")
    print(f"[+] View on Etherscan: {receipt['explorer_url']}")
    print(f"[+] Full receipt saved to: {saved_path}")
