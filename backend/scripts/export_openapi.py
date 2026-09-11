#!/usr/bin/env python3
"""Export the live OpenAPI document to api/openapi.v1.yaml.

The committed contract is generated from the implementation rather than
maintained beside it, so the two cannot drift. CI regenerates and diffs; a
change to a route or a schema that is not exported fails the build.

Usage:
    python scripts/export_openapi.py [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app
from app.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "api" / "openapi.v1.yaml"
HEADER = (
    "# Generated from the FastAPI implementation - do not edit by hand.\n"
    "# Regenerate with: python backend/scripts/export_openapi.py\n"
)


def build_document() -> str:
    settings = Settings(knowledge_dir=REPO_ROOT / "knowledge")
    document = create_app(settings).openapi()
    body = yaml.safe_dump(document, sort_keys=True, allow_unicode=True, width=100)
    return HEADER + body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero if the committed file is stale"
    )
    args = parser.parse_args()

    generated = build_document()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        if current != generated:
            print(f"{TARGET} is out of date; run python backend/scripts/export_openapi.py")
            return 1
        print(f"{TARGET} matches the implementation")
        return 0

    TARGET.write_text(generated, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
