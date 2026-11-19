#!/usr/bin/env python3
"""Copy the committed snapshot into public/data for client-side search."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data"
DEST = ROOT / "public" / "data"
NEEDED = [
    "meta.json",
    "contractors.json",
    "agencies.json",
    "naics.json",
    "recompetes.json",
    "opportunities.json",
    "index.json",
    "sponsors.json",
]


def main() -> None:
    missing = [name for name in NEEDED if not (SRC / name).exists()]
    if missing:
        raise SystemExit(
            "Missing data files: "
            + ", ".join(missing)
            + ". Run python3 scripts/update_data.py before starting the site."
        )
    DEST.mkdir(parents=True, exist_ok=True)
    for name in NEEDED:
        shutil.copyfile(SRC / name, DEST / name)


if __name__ == "__main__":
    main()
