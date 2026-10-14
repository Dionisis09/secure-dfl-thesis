"""Run the same experiment settings separately on all three image datasets."""

import argparse
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ("mnist", "fashion_mnist", "cifar10")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=["validation", "sensitivity", "network"], default="validation")
    parser.add_argument("--datasets", nargs="+", choices=DATASETS, default=list(DATASETS))
    parser.add_argument("--dry-run", action="store_true")
    args, extra = parser.parse_known_args()
    if extra and extra[0] == "--":
        extra = extra[1:]
    # Dataset and output paths belong to the suite, to avoid overwriting results.
    reserved = {"--dataset", "--datasets", "--output_dir", "--output-dir", "--experiment-id"}
    if any(token.split("=", 1)[0] in reserved for token in extra):
        parser.error("Set datasets with the suite's --datasets; output paths are managed per dataset.")
    for dataset in args.datasets:
        if args.workflow == "validation":
            command = [sys.executable, str(ROOT / "src/run_validation_experiments.py"), "--datasets", dataset, "--output_dir", f"results/validation/{dataset}"]
        elif args.workflow == "sensitivity":
            command = [sys.executable, str(ROOT / "src/run_adaptive_sensitivity.py"), "--dataset", dataset, "--output_dir", f"results/adaptive_sensitivity/{dataset}"]
        else:
            command = [sys.executable, str(ROOT / "platform_mvp/mnist_network_demo.py"), "--dataset", dataset, "--output-dir", f"platform_mvp/results/network/{dataset}"]
        command += extra
        print(shlex.join(command), flush=True)
        if not args.dry_run:
            subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
