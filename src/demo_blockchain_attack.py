"""Demo tamper attack against a saved blockchain audit ledger."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from blockchain.serialization import load_chain_json
from blockchain.verification import verify_chain_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Modify one blockchain block in memory and verify tamper detection."
    )
    parser.add_argument(
        "blockchain_json",
        type=Path,
        help="Path to results/blockchain/<experiment>_blockchain.json",
    )
    parser.add_argument(
        "--block_index",
        type=int,
        default=1,
        help="Block to tamper with. Default: 1, the first communication block.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    chain_data = load_chain_json(args.blockchain_json)
    blocks = chain_data.get("blocks", [])
    if not blocks:
        print("Chain INVALID")
        print("Reason: no blocks found")
        return 1

    target_index = min(max(args.block_index, 0), len(blocks) - 1)
    original_accuracy = float(blocks[target_index].get("test_accuracy", 0.0))
    blocks[target_index]["test_accuracy"] = original_accuracy + 1.0

    result = verify_chain_data(chain_data)
    if result.valid:
        print("Chain VALID")
        print("Tamper attack was not detected")
        return 1

    print("Chain INVALID")
    print(f"Verification status: {result.status}")
    print(f"Broken block: {result.broken_block}")
    print(f"Reason: {result.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
