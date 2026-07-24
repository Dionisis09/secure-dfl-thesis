"""Create a clean Secure DFL Platform MVP release bundle."""

from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime
from pathlib import Path


EXCLUDED_DIRS = {
    "__pycache__",
    ".runtime",
    "results",
    "deployment_keys",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def should_include(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def build_bundle(*, root: Path, output_dir: Path, name: str) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"{name}.zip"
    included: list[str] = []
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if should_include(path, root):
                arcname = Path(root.name) / path.relative_to(root)
                archive.write(path, arcname.as_posix())
                included.append(arcname.as_posix())
    manifest = {
        "bundle": str(bundle_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "files": included,
        "file_count": len(included),
        "excluded_dirs": sorted(EXCLUDED_DIRS),
    }
    (output_dir / f"{name}_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / f"{name}_manifest.md").write_text(
        "# Secure DFL Platform MVP Release Bundle\n\n"
        f"Bundle: `{bundle_path}`\n\n"
        f"Files included: `{len(included)}`\n\n"
        "Excluded generated/private folders: "
        + ", ".join(f"`{item}`" for item in sorted(EXCLUDED_DIRS))
        + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a clean platform_mvp release zip")
    parser.add_argument("--output-dir", default="results/release")
    parser.add_argument("--name", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent
    name = args.name or f"Secure_DFL_Platform_MVP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    manifest = build_bundle(root=root, output_dir=Path(args.output_dir), name=name)
    print(json.dumps({"status": "PASS", **manifest}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
