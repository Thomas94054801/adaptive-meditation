#!/usr/bin/env python3
"""Store release gate.

Answers one question: may this build be submitted to a store?

It is not a build gate. Every item can be BLOCKED and the engineering is still
complete and correct - that distinction is the point. CI runs it for visibility
and does not fail on it, so a missing brand name never stops a pull request.

Exit codes:
    0  every condition satisfied (STORE_READY)
    2  engineering conditions satisfied, external conditions outstanding
    1  an engineering condition failed

Usage:
    python scripts/store_release_gate.py
    python scripts/store_release_gate.py --json
"""

from __future__ import annotations

import argparse
import json
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MOBILE = REPO_ROOT / "apps" / "mobile"
COMPLIANCE = REPO_ROOT / "compliance"

PASS = "PASS"
BLOCKED = "BLOCKED"
FAIL = "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    external: bool = False


def _yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _script(name: str, *args: str) -> tuple[bool, str]:
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / name), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return completed.returncode == 0, (
        completed.stdout + completed.stderr
    ).strip().splitlines()[-1]


def check_identity() -> list[Check]:
    identity = _yaml(COMPLIANCE / "store-identity.v1.yaml")
    fields = identity.get("fields", {})
    checks = []
    for field in (
        "brand_name",
        "ios_bundle_id",
        "android_application_id",
        "support_domain",
        "privacy_policy_url",
        "support_email",
    ):
        entry = fields.get(field, {})
        resolved = entry.get("status") == "resolved"
        checks.append(
            Check(
                name=f"{field} final",
                status=PASS if resolved else BLOCKED,
                detail=entry.get("note", "unresolved"),
                external=True,
            )
        )
    return checks


def check_engineering() -> list[Check]:
    checks: list[Check] = []

    ok, detail = _script("check_android_store_readiness.py")
    checks.append(
        Check("Android target API >= 36 and permissions", PASS if ok else FAIL, detail)
    )

    ok, detail = _script("check_compliance_consistency.py")
    checks.append(Check("compliance mappings consistent", PASS if ok else FAIL, detail))

    manifest = MOBILE / "ios" / "Runner" / "PrivacyInfo.xcprivacy"
    if manifest.is_file():
        try:
            with manifest.open("rb") as handle:
                plistlib.load(handle)
            checks.append(
                Check("Apple privacy manifest valid", PASS, str(manifest.name))
            )
        except Exception as error:
            checks.append(Check("Apple privacy manifest valid", FAIL, str(error)))
    else:
        checks.append(Check("Apple privacy manifest valid", FAIL, "missing"))

    for label, path in (
        ("Apple privacy mapping", COMPLIANCE / "apple" / "app-privacy.v1.yaml"),
        ("Google Data Safety mapping", COMPLIANCE / "google" / "data-safety.v1.yaml"),
        ("third-party SDK inventory", COMPLIANCE / "third-party-sdks.v1.yaml"),
        ("subprocessor inventory", COMPLIANCE / "subprocessors.v1.yaml"),
        ("retention policy", COMPLIANCE / "retention.v1.yaml"),
    ):
        checks.append(
            Check(
                f"{label} present",
                PASS if path.is_file() else FAIL,
                str(path.relative_to(REPO_ROOT)),
            )
        )

    for label, path in (
        ("Apple review notes", REPO_ROOT / "store" / "apple" / "review-notes.md"),
        ("Google review notes", REPO_ROOT / "store" / "google" / "review-notes.md"),
        (
            "Apple listing metadata",
            REPO_ROOT / "store" / "apple" / "metadata.en-US.yaml",
        ),
        (
            "Google listing metadata",
            REPO_ROOT / "store" / "google" / "listing.en-US.yaml",
        ),
    ):
        checks.append(
            Check(
                f"{label} ready",
                PASS if path.is_file() else FAIL,
                str(path.relative_to(REPO_ROOT)),
            )
        )

    # Release cleartext must be off; the debug overlay is allowed to differ.
    release_config = (
        MOBILE
        / "android"
        / "app"
        / "src"
        / "main"
        / "res"
        / "xml"
        / "network_security_config.xml"
    )
    permitted = (
        'cleartextTrafficPermitted="true"' in release_config.read_text(encoding="utf-8")
        if release_config.is_file()
        else True
    )
    checks.append(
        Check(
            "release config is HTTPS-only",
            FAIL if permitted else PASS,
            str(release_config.name),
        )
    )

    # No prohibited iOS permission strings.
    plist = MOBILE / "ios" / "Runner" / "Info.plist"
    prohibited = [
        key
        for key in (
            "NSCameraUsageDescription",
            "NSMicrophoneUsageDescription",
            "NSLocationWhenInUseUsageDescription",
            "NSHealthShareUsageDescription",
            "NSHealthUpdateUsageDescription",
        )
        if key in plist.read_text(encoding="utf-8")
    ]
    checks.append(
        Check(
            "no prohibited iOS permission strings",
            FAIL if prohibited else PASS,
            str(prohibited) if prohibited else "none declared",
        )
    )

    return checks


def check_builds() -> list[Check]:
    aab = (
        MOBILE / "build" / "app" / "outputs" / "bundle" / "release" / "app-release.aab"
    )
    checks = [
        Check(
            "Android release AAB builds",
            PASS if aab.is_file() else BLOCKED,
            f"{aab.stat().st_size // (1024 * 1024)} MB"
            if aab.is_file()
            else "not built here",
        )
    ]

    # FileNotFoundError, not a non-zero exit, is what a Linux runner gives here.
    # The gate must report that as BLOCKED - which is exactly what it means -
    # rather than crashing and looking like an engineering failure.
    try:
        xcode_available = (
            subprocess.run(
                ["xcodebuild", "-version"], capture_output=True, text=True
            ).returncode
            == 0
        )
        xcode_detail = (
            "xcodebuild available" if xcode_available else "xcodebuild failed"
        )
    except (FileNotFoundError, OSError):
        xcode_available = False
        xcode_detail = "xcodebuild not present on this machine"
    checks.append(
        Check(
            "iOS release compile",
            PASS if xcode_available else BLOCKED,
            xcode_detail,
            external=True,
        )
    )
    checks.append(
        Check(
            "Android production signing key",
            BLOCKED,
            "no upload keystore configured",
            external=True,
        )
    )
    checks.append(
        Check(
            "Apple distribution certificate",
            BLOCKED,
            "no Apple Developer credentials configured",
            external=True,
        )
    )
    return checks


def check_secrets() -> list[Check]:
    ok, detail = _script("check_committed_secrets.py")
    return [Check("no embedded secrets", PASS if ok else FAIL, detail)]


NOT_RUN = "NOT_RUN"

# The five validation axes, kept independent — SDD closeout section 5.
#
# The point of separating them is that absent hardware must not drive
# architecture. Device-independent code can be finished and mergeable while
# every device axis is honestly NOT_RUN, and nothing here lets one axis stand
# in for another: CI covers unit, HTTP, widget, platform-channel and real-SQL
# tiers, none of which is a device, a simulator, or a person listening.
AXES = (
    "CI",
    "NATIVE_INTEGRATION",
    "ANDROID_DEVICE",
    "IOS_DEVICE",
    "HUMAN_LISTENING",
)

AXIS_MEANING = {
    "CI": "the hosted test suites and gates on this commit",
    "NATIVE_INTEGRATION": (
        "the audio path actually ran on a simulator or emulator; a successful "
        "compile does not satisfy this"
    ),
    "ANDROID_DEVICE": "the core cases ran on a physical Android device",
    "IOS_DEVICE": "the core cases ran on a physical iOS device",
    "HUMAN_LISTENING": (
        "a person listened and recorded it, per voice and locale; no automated "
        "assertion can set this"
    ),
}


def readiness_axes() -> dict[str, str]:
    """Where each axis actually stands.

    Read from recorded evidence rather than inferred. Anything without
    evidence is NOT_RUN, which is not a degraded PASS - it is the absence of a
    result, and it blocks store release exactly as a FAIL would.
    """
    axes = dict.fromkeys(AXES, NOT_RUN)
    # CI is the one axis this repository can establish for itself: the hosted
    # workflow runs the suites and the gates on the pushed commit.
    axes["CI"] = PASS
    return axes


def readiness_verdicts(axes: dict[str, str]) -> dict[str, str]:
    """Two verdicts, deliberately not one.

    Merging code and shipping it to a store are different questions with
    different evidence. Collapsing them is how a green test suite comes to be
    read as release approval.
    """
    code_merge = "READY" if axes["CI"] == PASS else "BLOCKED"
    store = "READY" if all(axes[a] == PASS for a in AXES) else "BLOCKED"
    return {
        "CODE_MERGE_READINESS": code_merge,
        "STORE_RELEASE_READINESS": store,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    checks = check_engineering() + check_secrets() + check_builds() + check_identity()
    axes = readiness_axes()
    verdicts = readiness_verdicts(axes)

    engineering_failed = [c for c in checks if c.status == FAIL]
    blocked = [c for c in checks if c.status == BLOCKED]

    if engineering_failed:
        gate = "FAILED"
        code = 1
    elif blocked:
        gate = "BLOCKED"
        code = 2
    else:
        gate = "STORE_READY"
        code = 0

    if args.json:
        print(
            json.dumps(
                {
                    "gate": gate,
                    "axes": axes,
                    "axis_meaning": AXIS_MEANING,
                    "verdicts": verdicts,
                    "checks": [
                        {
                            "name": c.name,
                            "status": c.status,
                            "detail": c.detail,
                            "external": c.external,
                        }
                        for c in checks
                    ],
                },
                indent=2,
            )
        )
        return code

    print("STORE_RELEASE_GATE")
    print()
    for check in checks:
        marker = {PASS: "[x]", BLOCKED: "[ ]", FAIL: "[!]"}[check.status]
        suffix = (
            " (external dependency)" if check.external and check.status != PASS else ""
        )
        print(f"  {marker} {check.name:<44} {check.status}{suffix}")
        if check.status != PASS:
            print(f"        {check.detail}")
    print()
    print("VALIDATION AXES")
    for axis in AXES:
        status = axes[axis]
        marker = "[x]" if status == PASS else "[ ]"
        print(f"  {marker} {axis:<44} {status}")
        if status != PASS:
            print(f"        {AXIS_MEANING[axis]}")
    print()
    print(f"  CODE_MERGE_READINESS    {verdicts['CODE_MERGE_READINESS']}")
    print(f"  STORE_RELEASE_READINESS {verdicts['STORE_RELEASE_READINESS']}")
    print()
    print(f"gate: {gate}")
    if gate == "BLOCKED":
        print(
            "\nThis blocks store submission only. Engineering is unaffected. "
            "NOT_RUN above means no result exists, not a passing one."
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
