# Face ID + Blockchain Verification Pipeline

An end-to-end CLI pipeline that: detects and encodes a face in a photo,
performs a **genuine** reverse image search to check whether that exact
photo (or a close visual match) already exists publicly on the web, and
writes a tamper-evident, re-verifiable fingerprint of the finding to the
Ethereum Sepolia testnet.

This project answers one question: **"does this photo already exist
publicly somewhere?"** — it does not attempt to identify who the person
in the photo is.

## Pipeline Overview

```
Input Photo
    |
    v
[1] Face Detection + Encoding (InsightFace)
    -> outputs/face_embedding.json
    |
    v
[2] Genuine Reverse Image Search (SerpApi / Google Lens
    + perceptual hashing for crop/resize/compression robustness)
    -> outputs/match_result.json
    |
    v
[3] Blockchain Notarization (Ethereum Sepolia testnet)
    -> outputs/tx_receipt.json
```

Steps 1 and 2 are intentionally loosely coupled: face embeddings are not
fed into the reverse image search (no reverse-image API accepts a raw
face vector as a query -- they match on whole-image visual similarity).
Instead, both outputs are combined and hashed together in Step 3, so the
final on-chain record ties together "a face was detected with encoding
X" and "this photo was found at URL Y with similarity Z."

## What Blockchain Was Used

**Ethereum Sepolia testnet.** No smart contract is used -- the SHA-256
hash of the evidence record is embedded directly in a transaction's
`data` field (a zero-value transaction sent from the wallet to itself).
Once mined, this is a permanent, publicly viewable, tamper-evident
record: anyone can look up the transaction hash on
[Sepolia Etherscan](https://sepolia.etherscan.io), decode the data
field, and compare it against an independently recomputed hash.

## Setup

### 1. Clone and install dependencies

```bash
git clone <this-repo-url>
cd faceid-blockchain-verify
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | How to get it |
|---|---|
| `SERPAPI_API_KEY` | Free tier account at [serpapi.com](https://serpapi.com/dashboard) (100 searches/month free) |
| `SEPOLIA_RPC_URL` | A free public RPC endpoint, e.g. `https://ethereum-sepolia-rpc.publicnode.com` -- no signup needed |
| `WALLET_PRIVATE_KEY` | Export from MetaMask (Account details -> Show private key). **Use a wallet holding only testnet funds.** |

### 3. Get free Sepolia testnet ETH

Use a faucet such as:
- https://cloud.google.com/application/web3/faucet/ethereum/sepolia
- https://www.alchemy.com/faucets/ethereum-sepolia

This is free, fake ETH for testing -- no real money involved.

## Running the Pipeline

### Full pipeline, one command:

```bash
python pipeline/run_pipeline.py samples/your_photo.jpg
```

This runs all three steps in order and writes:
- `outputs/face_embedding.json`
- `outputs/match_result.json`
- `outputs/tx_receipt.json`

### Or run each step individually:

```bash
python pipeline/face_encode.py samples/your_photo.jpg outputs/face_embedding.json
python pipeline/reverse_search.py samples/your_photo.jpg outputs/match_result.json
python pipeline/blockchain_notarize.py outputs/face_embedding.json outputs/match_result.json outputs/tx_receipt.json
```

### Re-verifying a record later

Anyone with a copy of `tx_receipt.json` can independently confirm the
record hasn't been tampered with, using only public Sepolia
infrastructure -- no API keys or wallet access required:

```bash
python verify.py outputs/tx_receipt.json
```

This re-fetches the transaction from chain, extracts the embedded hash,
recomputes the hash from the stored evidence record, and confirms they
match.

## Project Structure

```
faceid-blockchain-verify/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── pipeline/
│   ├── face_encode.py           # Step 1: face detection + encoding
│   ├── reverse_search.py        # Step 2: reverse image search + perceptual hashing
│   ├── blockchain_notarize.py   # Step 3: hash + write to Sepolia
│   └── run_pipeline.py          # orchestrates all 3 steps
├── verify.py                    # standalone re-verification script
├── samples/                     # example input images
└── outputs/                     # generated per-run JSON artifacts
```

## Design Choices

- **Face detection/encoding: InsightFace (buffalo_l)** -- chosen over
  `face_recognition`/dlib for easier installation (no C++ build step)
  and higher-dimensional (512-d vs 128-d) embeddings.
- **Reverse image search: SerpApi's Google Lens engine** -- returns
  real, live visual-match results with actual source URLs. Free tier
  covers demo/testing use.
- **Perceptual hashing (pHash) via the `imagehash` library** is used to
  re-rank Google Lens's candidate matches by actual visual similarity
  (Hamming distance), which adds robustness to mild crops, resizing,
  and compression that pixel-exact hashing would miss.
- **Blockchain: Ethereum Sepolia testnet**, no smart contract --
  keeping the on-chain footprint to a single transaction's `data` field
  keeps the system simple, cheap (free, testnet ETH), and still fully
  publicly verifiable via any Ethereum block explorer.
- **Biometric data handling**: the raw 512-d face embedding vector is
  never written to the blockchain -- only its SHA-256 hash is included
  in the on-chain record, since embeddings are sensitive biometric data
  and Sepolia is a public, permanent, unencrypted ledger.

## Known Limitations

- **Search coverage is bounded by the search engine's index.** A "no
  match found" result does not prove an image has never been posted
  publicly -- it only means it wasn't indexed by Google Lens at the
  time of the search.
- **Free-tier API limits.** SerpApi's free tier caps monthly searches;
  heavy use requires a paid plan.
- **Perceptual hashing tolerance is bounded.** pHash handles resizing,
  compression, and mild cropping well, but will not reliably match
  images that have been heavily cropped, rotated, mirrored, or
  regenerated/altered by AI.
- **The blockchain proves timestamp + integrity, not ground truth.**
  Notarizing a hash proves that a specific finding existed at a specific
  time and hasn't been altered since -- it does not independently verify
  that the reverse-search match itself is correct.
- **Third-party image hosting dependency.** To let Google Lens fetch the
  input image, the pipeline temporarily uploads it to a public file host
  (catbox.moe). Uploaded images are **not automatically deleted** by
  this host and remain publicly accessible at a guessable-if-leaked URL
  until manually removed. Only run this pipeline on images you're
  comfortable being made public.
- **Sepolia is a test network.** While transactions on it are real and
  publicly verifiable today, testnets are occasionally reset by their
  maintainers, which could theoretically affect very long-term
  verifiability. For production use, mainnet or a purpose-built
  timestamping service (e.g. OpenTimestamps) would be more durable.
- **Single-face assumption.** If multiple faces are detected, the
  pipeline encodes only the largest (primary) face; other detected
  faces are counted but not individually processed.

## Demo Video

[Link to screen recording demonstrating the full pipeline running end-to-end]
