#!/usr/bin/env python3
"""Committed-credential scan.

Extended in Program003 to the file types a mobile release introduces: Dart,
plist, Gradle, xcconfig, JSON and YAML. A server-side-only scanner would have
missed a key pasted into a Gradle file or an Info.plist, which is exactly where
mobile secrets end up.

Deliberately narrow on value patterns. A scanner that fires on the word
"password" trains people to ignore it, and an ignored scanner is worse than none.

Usage:
    python scripts/check_committed_secrets.py
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Filenames that should never be tracked, whatever they contain.
FORBIDDEN_NAMES = re.compile(
    r"(^|/)("
    r"\.env(\.[^/]*)?"
    r"|.*\.(pem|p8|p12|key|keystore|jks|mobileprovision|cer|certSigningRequest)"
    r"|.*service-account.*\.json"
    r"|.*google-services\.json"
    r"|.*GoogleService-Info\.plist"
    r"|.*oci_api_key.*"
    r"|key\.properties"
    r"|id_rsa|id_ed25519"
    r")$"
)

VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("AWS secret", re.compile(r"aws_secret_access_key\s*=\s*\S{20,}", re.I)),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("Anthropic-style key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Apple auth key filename", re.compile(r"AuthKey_[A-Z0-9]{10}\.p8")),
    ("service account json", re.compile(r'"type"\s*:\s*"service_account"')),
    ("OCI ocid", re.compile(r"ocid1\.(tenancy|user)\.oc1\.\.[a-z0-9]{20,}")),
    (
        "OCI key fingerprint",
        re.compile(r"^\s*fingerprint\s*=\s*([0-9a-f]{2}:){15}[0-9a-f]{2}", re.M),
    ),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    (
        "hardcoded db password in url",
        re.compile(
            r"(postgres(ql)?(\+\w+)?)://[^\s:/@]+:(?!\$|\{|change-me|adaptive@)[^\s:/@]{3,}@", re.I
        ),
    ),
)

# Patterns that only make sense for particular file types. Scoped, because an
# assignment that reads as a secret in an xcconfig is an ordinary template line
# in a .env.example.
SUFFIX_PATTERNS: tuple[tuple[tuple[str, ...], str, re.Pattern[str]], ...] = (
    (
        (".gradle", ".kts", ".properties"),
        "gradle signing password",
        re.compile(
            r"(storePassword|keyPassword)\s*[=:]\s*[\"']?(?!\$|System\.|\s*$)[^\"'\s]{3,}", re.I
        ),
    ),
    (
        (".xcconfig",),
        "xcconfig embedded key",
        re.compile(r"^\s*[A-Z_]*(API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*(?!\$)\S{8,}", re.M),
    ),
    (
        (".dart",),
        "hardcoded key literal in Dart",
        re.compile(r"(apiKey|secretKey|accessToken)\s*=\s*[\"'][A-Za-z0-9_\-]{16,}[\"']"),
    ),
)

# Values that look like assignments but are documented placeholders. Listed
# explicitly so a real secret cannot hide behind a vague allowlist.
PLACEHOLDER_VALUES = (
    "change-me",
    "changeme",
    "your-",
    "example",
    "placeholder",
    "xxxxx",
)

# This scanner contains every pattern it looks for, so it must exempt itself.
SELF_EXEMPT = {
    "scripts/check_committed_secrets.py",
    ".github/workflows/ci.yml",
}

# Extensions Program003 added. Listed so the coverage is auditable rather than
# implied by "we read every text file".
COVERED_SUFFIXES = (
    ".dart",
    ".plist",
    ".xcprivacy",
    ".gradle",
    ".kts",
    ".xcconfig",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".xml",
    ".properties",
    ".pbxproj",
    ".md",
    ".txt",
    ".toml",
    ".sh",
    ".env.example",
)


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True, cwd=REPO_ROOT
    ).stdout.decode()
    return [name for name in out.split("\0") if name]


def main() -> int:
    failures: list[str] = []
    scanned = 0
    covered = 0

    for name in tracked_files():
        if name in SELF_EXEMPT:
            continue
        if FORBIDDEN_NAMES.search(name) and not name.endswith(".env.example"):
            failures.append(f"{name}: forbidden filename")
            continue
        path = REPO_ROOT / name
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        scanned += 1
        if name.endswith(COVERED_SUFFIXES):
            covered += 1
        for label, pattern in VALUE_PATTERNS:
            match = pattern.search(content)
            if match:
                failures.append(f"{name}: {label}: {match.group(0)[:48]!r}")

        for suffixes, label, pattern in SUFFIX_PATTERNS:
            if not name.endswith(suffixes):
                continue
            match = pattern.search(content)
            if match and not any(
                placeholder in match.group(0).lower() for placeholder in PLACEHOLDER_VALUES
            ):
                failures.append(f"{name}: {label}: {match.group(0)[:48]!r}")

    print(f"  scanned {scanned} text files ({covered} in the covered extension set)")
    if failures:
        print("  committed credential material found:")
        for line in failures:
            print(f"    {line}")
        return 1
    print("credential scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
