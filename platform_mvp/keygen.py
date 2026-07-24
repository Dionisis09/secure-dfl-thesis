"""Generate Ed25519 node identities for a Secure DFL deployment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from secure_dfl_platform.key_management import write_node_keys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Ed25519 private keys and a trusted public-key manifest"
    )
    parser.add_argument(
        "--nodes",
        default="node0,node1,node2",
        help="Comma-separated node ids, for example node0,node1,node2",
    )
    parser.add_argument(
        "--output-dir",
        default="deployment_keys",
        help="Directory where keys and trusted_keys.json will be written",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    node_ids = [item.strip() for item in args.nodes.split(",") if item.strip()]
    metadata = write_node_keys(
        node_ids=node_ids,
        output_dir=Path(args.output_dir),
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "nodes": sorted(metadata),
                "output_dir": str(Path(args.output_dir).resolve()),
                "trusted_keys_file": str(
                    (Path(args.output_dir) / "trusted_keys.json").resolve()
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
