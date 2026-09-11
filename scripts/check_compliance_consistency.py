#!/usr/bin/env python3
"""Compliance consistency gate.

Five documents describe the same data from different angles:

    data-inventory  <->  Apple App Privacy
                    <->  Google Data Safety
                    <->  third-party SDK inventory
                    <->  subprocessors

Four of them are filed with a store or published to users. Left unchecked they
drift, and a drifted document is not a stale note - it is a false declaration to
Apple, to Google, or to the person reading the privacy policy.

This fails CI on:
  - a data-inventory category with no Apple mapping;
  - a data-inventory category with no Google mapping;
  - a mapping that references an inventory path that does not exist;
  - the Apple privacy manifest disagreeing with its own audit;
  - a package in pubspec.yaml missing from the SDK inventory;
  - a prohibited SDK appearing in pubspec.yaml;
  - deletable/tracking answers contradicting each other across documents.

Usage:
    python scripts/check_compliance_consistency.py
"""

from __future__ import annotations

import plistlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPLIANCE = REPO_ROOT / "compliance"
INVENTORY = COMPLIANCE / "data-inventory.v1.yaml"
APPLE_PRIVACY = COMPLIANCE / "apple" / "app-privacy.v1.yaml"
APPLE_AUDIT = COMPLIANCE / "apple" / "privacy-manifest-audit.v1.yaml"
GOOGLE_SAFETY = COMPLIANCE / "google" / "data-safety.v1.yaml"
SDK_INVENTORY = COMPLIANCE / "third-party-sdks.v1.yaml"
SUBPROCESSORS = COMPLIANCE / "subprocessors.v1.yaml"
PRIVACY_MANIFEST = REPO_ROOT / "apps" / "mobile" / "ios" / "Runner" / "PrivacyInfo.xcprivacy"
PUBSPEC = REPO_ROOT / "apps" / "mobile" / "pubspec.yaml"

# Inventory leaves that describe collected data and therefore need a store
# mapping. Sections that describe a decision rather than a collection
# (sensors, health, commerce) are excluded by name, not by guesswork.
MAPPABLE_SECTIONS = ("identity_guest", "wellness")


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SystemExit(f"{path} does not contain a mapping")
    return data


def inventory_categories(inventory: dict[str, Any]) -> set[str]:
    """Dotted paths of every collected category needing a store answer."""
    found: set[str] = set()
    v1 = inventory.get("v1", {})
    for section in MAPPABLE_SECTIONS:
        for name, entry in (v1.get(section) or {}).items():
            if isinstance(entry, dict) and entry.get("collected") is True:
                found.add(f"v1.{section}.{name}")
    return found


def mapped_refs(document: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for row in document.get("data_types", []):
        ref = row.get("inventory_ref")
        if isinstance(ref, str):
            refs.add(ref)
        elif isinstance(ref, list):
            refs.update(str(item) for item in ref)
    return refs


def check_store_mappings(failures: list[str], results: list[str]) -> None:
    inventory = load(INVENTORY)
    categories = inventory_categories(inventory)
    if not categories:
        failures.append("data inventory declares no collected category; check the parser")
        return

    for label, path in (("Apple App Privacy", APPLE_PRIVACY), ("Google Data Safety", GOOGLE_SAFETY)):
        refs = mapped_refs(load(path))
        missing = sorted(categories - refs)
        if missing:
            failures.append(f"{label} has no mapping for: {missing}")
        unknown = sorted(ref for ref in refs if ref not in categories)
        if unknown:
            failures.append(f"{label} references unknown inventory paths: {unknown}")
        if not missing and not unknown:
            results.append(f"{label}: {len(refs)} categories mapped, all resolve")


def check_tracking_agreement(failures: list[str], results: list[str]) -> None:
    apple = load(APPLE_PRIVACY)
    google = load(GOOGLE_SAFETY)
    inventory = load(INVENTORY)

    if apple.get("tracking", {}).get("app_tracks_users") is not False:
        failures.append("Apple mapping claims tracking; V1 must not track")
    if google.get("summary", {}).get("data_shared") is not False:
        failures.append("Google mapping claims data sharing; V1 must not share")

    # Advertising use is declared false throughout the inventory; a store
    # document contradicting that is the mismatch worth catching.
    for row in apple.get("data_types", []):
        if row.get("used_for_tracking"):
            failures.append(f"Apple: {row.get('apple_subtype')} marked as tracking")
    for row in google.get("data_types", []):
        if row.get("shared"):
            failures.append(f"Google: {row.get('play_type')} marked as shared")

    for section in MAPPABLE_SECTIONS:
        for name, entry in (inventory.get("v1", {}).get(section) or {}).items():
            if isinstance(entry, dict) and entry.get("advertising_use") is True:
                failures.append(f"inventory v1.{section}.{name} allows advertising use")
    if not failures:
        results.append("tracking/sharing answers agree across all three documents")


def check_deletion_agreement(failures: list[str], results: list[str]) -> None:
    apple = load(APPLE_PRIVACY)
    google = load(GOOGLE_SAFETY)
    if google.get("summary", {}).get("user_can_request_deletion") is not True:
        failures.append("Google mapping does not offer deletion")
    for row in apple.get("data_types", []):
        if row.get("collected") and row.get("deletable") is not True:
            failures.append(f"Apple: {row.get('apple_subtype')} collected but not deletable")
    for row in google.get("data_types", []):
        if row.get("collected") and row.get("deletion_supported") is not True:
            failures.append(f"Google: {row.get('play_type')} collected but not deletable")
    results.append("every collected category is declared deletable in both mappings")


def check_privacy_manifest(failures: list[str], results: list[str]) -> None:
    if not PRIVACY_MANIFEST.is_file():
        failures.append(f"{PRIVACY_MANIFEST} is missing")
        return
    try:
        with PRIVACY_MANIFEST.open("rb") as handle:
            manifest = plistlib.load(handle)
    except Exception as error:  # noqa: BLE001 - any parse failure is a failure
        failures.append(f"privacy manifest does not parse: {error}")
        return

    audit = load(APPLE_AUDIT).get("app_manifest", {})

    if manifest.get("NSPrivacyTracking") != audit.get("tracking"):
        failures.append("privacy manifest tracking disagrees with the audit")

    manifest_apis = [
        entry.get("NSPrivacyAccessedAPIType")
        for entry in manifest.get("NSPrivacyAccessedAPITypes", [])
    ]
    audit_apis = audit.get("accessed_api_types") or []
    if sorted(filter(None, manifest_apis)) != sorted(audit_apis):
        failures.append(
            f"privacy manifest accessed APIs {manifest_apis} disagree with audit {audit_apis}"
        )

    manifest_types = sorted(
        entry.get("NSPrivacyCollectedDataType", "")
        for entry in manifest.get("NSPrivacyCollectedDataTypes", [])
    )
    audit_types = sorted(row.get("type", "") for row in audit.get("collected_data_types", []))
    if manifest_types != audit_types:
        failures.append(
            f"privacy manifest data types {manifest_types} disagree with audit {audit_types}"
        )

    for entry in manifest.get("NSPrivacyCollectedDataTypes", []):
        if entry.get("NSPrivacyCollectedDataTypeTracking"):
            failures.append("privacy manifest marks a data type as tracking")
        if entry.get("NSPrivacyCollectedDataType") == "NSPrivacyCollectedDataTypeHealthFitness":
            failures.append(
                "privacy manifest declares Health and Fitness; HealthKit is not enabled in V1"
            )

    results.append(
        f"privacy manifest parses and agrees with the audit "
        f"({len(manifest_types)} data types, {len(manifest_apis)} required-reason APIs)"
    )


def check_sdk_inventory(failures: list[str], results: list[str]) -> None:
    sdks = load(SDK_INVENTORY)
    declared = {row["package"] for row in sdks.get("sdks", [])}
    declared |= {row["package"] for row in sdks.get("runtime", [])}
    declared |= set(sdks.get("dart_only_dependencies", []))

    pubspec = load(PUBSPEC)
    direct = set(pubspec.get("dependencies", {}) or {}) - {"flutter"}
    missing = sorted(direct - declared)
    if missing:
        failures.append(f"pubspec dependencies missing from the SDK inventory: {missing}")

    prohibited = sdks.get("prohibited_in_v1", [])
    pubspec_text = PUBSPEC.read_text(encoding="utf-8").lower()
    for name in prohibited:
        token = name.replace("_sdk", "").replace("_", "")
        if token and re.search(rf"\b{re.escape(token)}\b", pubspec_text):
            failures.append(f"prohibited SDK appears in pubspec: {name}")

    if not missing:
        results.append(f"SDK inventory covers all {len(direct)} direct dependencies")


def check_subprocessors(failures: list[str], results: list[str]) -> None:
    data = load(SUBPROCESSORS)
    processors = data.get("subprocessors", [])
    if not processors:
        failures.append("subprocessor inventory is empty; the service is hosted somewhere")
        return
    for row in processors:
        for field in ("name", "purpose", "data_categories", "required_for_service"):
            if field not in row:
                failures.append(f"subprocessor {row.get('name')!r} is missing {field}")
    results.append(f"{len(processors)} subprocessor(s) declared with required fields")


def main() -> int:
    failures: list[str] = []
    results: list[str] = []

    check_store_mappings(failures, results)
    check_tracking_agreement(failures, results)
    check_deletion_agreement(failures, results)
    check_privacy_manifest(failures, results)
    check_sdk_inventory(failures, results)
    check_subprocessors(failures, results)

    for line in results:
        print(f"  ok   {line}")
    if failures:
        for line in failures:
            print(f"  FAIL {line}")
        return 1
    print("compliance consistency: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
