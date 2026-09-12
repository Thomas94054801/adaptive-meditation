"""The store-readiness gates - SDD_PROGRAM003 sections 10, 12, 38, 39.

These test the checkers, not just run them. A gate that cannot fail is not a
gate, so each one is shown rejecting the thing it exists to catch.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
COMPLIANCE = REPO_ROOT / "compliance"
MOBILE = REPO_ROOT / "apps" / "mobile"


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
    )


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# --- android ------------------------------------------------------------------


def test_android_store_readiness_passes() -> None:
    result = run_script("check_android_store_readiness.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "android store readiness: PASS" in result.stdout


def test_the_android_target_is_pinned_not_inherited() -> None:
    """Inheriting the right value today does not guarantee it after an upgrade."""
    gradle = (MOBILE / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert "targetSdk = 36" in gradle
    assert "targetSdk = flutter.targetSdkVersion" not in gradle
    assert "compileSdk = flutter.compileSdkVersion" not in gradle


def test_the_gate_rejects_an_inherited_target(tmp_path: Path) -> None:
    """The check must fail on the exact pattern Program002 shipped."""
    sys.path.insert(0, str(SCRIPTS))
    from check_android_store_readiness import (  # type: ignore[import-not-found]
        CheckFailure,
        _gradle_int,
    )

    with pytest.raises(CheckFailure, match="inherited"):
        _gradle_int("    targetSdk = flutter.targetSdkVersion\n", "targetSdk")


def test_the_gate_rejects_a_low_target() -> None:
    sys.path.insert(0, str(SCRIPTS))
    import check_android_store_readiness as gate  # type: ignore[import-not-found]

    results: list[str] = []
    original = gate.GRADLE.read_text(encoding="utf-8")
    try:
        gate.GRADLE.write_text(original.replace("targetSdk = 36", "targetSdk = 34"))
        with pytest.raises(gate.CheckFailure, match="targetSdk is 34"):
            gate.check_sdk_levels(results)
    finally:
        gate.GRADLE.write_text(original)


def test_the_gate_rejects_a_prohibited_permission() -> None:
    sys.path.insert(0, str(SCRIPTS))
    import check_android_store_readiness as gate  # type: ignore[import-not-found]

    manifest = """<?xml version="1.0"?>
    <manifest xmlns:android="http://schemas.android.com/apk/res/android">
      <uses-permission android:name="android.permission.CAMERA"/>
    </manifest>"""
    with pytest.raises(gate.CheckFailure, match="prohibited"):
        gate.check_permissions(manifest, "test", [])


def test_release_cleartext_is_off() -> None:
    config = (
        MOBILE / "android" / "app" / "src" / "main" / "res" / "xml" / "network_security_config.xml"
    ).read_text(encoding="utf-8")
    assert 'cleartextTrafficPermitted="false"' in config
    assert 'cleartextTrafficPermitted="true"' not in config


def test_the_debug_overlay_is_not_in_the_release_source_set() -> None:
    """Loopback cleartext must exist only in src/debug."""
    debug = (
        MOBILE / "android" / "app" / "src" / "debug" / "res" / "xml" / "network_security_config.xml"
    )
    assert debug.is_file()
    assert 'cleartextTrafficPermitted="true"' in debug.read_text(encoding="utf-8")


def test_backups_do_not_carry_the_identity() -> None:
    rules = (
        MOBILE / "android" / "app" / "src" / "main" / "res" / "xml" / "data_extraction_rules.xml"
    ).read_text(encoding="utf-8")
    assert "<cloud-backup>" in rules
    assert "<device-transfer>" in rules
    manifest = (MOBILE / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(
        encoding="utf-8"
    )
    assert 'android:allowBackup="false"' in manifest


# --- ios ----------------------------------------------------------------------


def test_the_privacy_manifest_exists_and_parses() -> None:
    manifest_path = MOBILE / "ios" / "Runner" / "PrivacyInfo.xcprivacy"
    assert manifest_path.is_file()
    with manifest_path.open("rb") as handle:
        manifest = plistlib.load(handle)
    assert manifest["NSPrivacyTracking"] is False
    assert manifest["NSPrivacyTrackingDomains"] == []


def test_the_privacy_manifest_declares_no_health_data() -> None:
    """HealthKit is not enabled, so declaring the category would be inaccurate."""
    with (MOBILE / "ios" / "Runner" / "PrivacyInfo.xcprivacy").open("rb") as handle:
        manifest = plistlib.load(handle)
    types = {
        entry["NSPrivacyCollectedDataType"] for entry in manifest["NSPrivacyCollectedDataTypes"]
    }
    assert "NSPrivacyCollectedDataTypeHealthFitness" not in types


def test_the_privacy_manifest_is_registered_in_the_xcode_project() -> None:
    """A manifest that is not in the Resources phase never ships."""
    pbxproj = (MOBILE / "ios" / "Runner.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
    assert pbxproj.count("PrivacyInfo.xcprivacy") >= 4  # file ref, build file, group, phase
    assert "PrivacyInfo.xcprivacy in Resources" in pbxproj


def test_no_prohibited_ios_permission_string() -> None:
    plist = (MOBILE / "ios" / "Runner" / "Info.plist").read_text(encoding="utf-8")
    for key in (
        "NSCameraUsageDescription",
        "NSMicrophoneUsageDescription",
        "NSLocationWhenInUseUsageDescription",
        "NSHealthShareUsageDescription",
        "NSHealthUpdateUsageDescription",
        "NSContactsUsageDescription",
        "NSMotionUsageDescription",
    ):
        assert key not in plist, key


# --- compliance consistency ---------------------------------------------------


def test_compliance_consistency_passes() -> None:
    result = run_script("check_compliance_consistency.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "compliance consistency: PASS" in result.stdout


def test_consistency_fails_when_a_mapping_goes_missing(tmp_path: Path) -> None:
    """Remove one Apple mapping and the gate must notice."""
    sys.path.insert(0, str(SCRIPTS))
    import check_compliance_consistency as gate  # type: ignore[import-not-found]

    original = gate.APPLE_PRIVACY.read_text(encoding="utf-8")
    document = yaml.safe_load(original)
    document["data_types"] = [
        row for row in document["data_types"] if row.get("inventory_ref") is None
    ]
    try:
        gate.APPLE_PRIVACY.write_text(yaml.safe_dump(document))
        failures: list[str] = []
        gate.check_store_mappings(failures, [])
        assert any("no mapping for" in failure for failure in failures), failures
    finally:
        gate.APPLE_PRIVACY.write_text(original)


def test_consistency_fails_when_the_manifest_drifts_from_the_audit() -> None:
    sys.path.insert(0, str(SCRIPTS))
    import check_compliance_consistency as gate  # type: ignore[import-not-found]

    original = gate.PRIVACY_MANIFEST.read_bytes()
    try:
        with gate.PRIVACY_MANIFEST.open("rb") as handle:
            manifest = plistlib.load(handle)
        manifest["NSPrivacyTracking"] = True
        with gate.PRIVACY_MANIFEST.open("wb") as handle:
            plistlib.dump(manifest, handle)

        failures: list[str] = []
        gate.check_privacy_manifest(failures, [])
        assert any("tracking disagrees" in failure for failure in failures), failures
    finally:
        gate.PRIVACY_MANIFEST.write_bytes(original)


def test_every_compliance_document_exists_and_parses() -> None:
    for path in (
        COMPLIANCE / "data-inventory.v1.yaml",
        COMPLIANCE / "permissions.v1.yaml",
        COMPLIANCE / "third-party-sdks.v1.yaml",
        COMPLIANCE / "subprocessors.v1.yaml",
        COMPLIANCE / "retention.v1.yaml",
        COMPLIANCE / "audience.v1.yaml",
        COMPLIANCE / "store-identity.v1.yaml",
        COMPLIANCE / "apple" / "app-privacy.v1.yaml",
        COMPLIANCE / "apple" / "privacy-manifest-audit.v1.yaml",
        COMPLIANCE / "google" / "data-safety.v1.yaml",
    ):
        assert path.is_file(), path
        assert load(path), path


def test_the_subprocessor_list_has_no_hypothetical_entries() -> None:
    """Listing a processor that processes nothing makes the policy inaccurate."""
    data = load(COMPLIANCE / "subprocessors.v1.yaml")
    names = {row["name"].lower() for row in data["subprocessors"]}
    for hypothetical in ("openai", "anthropic", "claude", "elevenlabs", "google analytics"):
        assert not any(hypothetical in name for name in names), hypothetical


def test_the_audience_policy_excludes_children() -> None:
    audience = load(COMPLIANCE / "audience.v1.yaml")["target_audience"]
    assert audience["designed_for_children"] is False
    assert audience["kids_category"] is False
    assert audience["child_profiling"] is False


# --- secrets and the release gate ---------------------------------------------


def test_no_committed_secret() -> None:
    result = run_script("check_committed_secrets.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "credential scan: clean" in result.stdout


def test_the_secret_scanner_covers_mobile_file_types() -> None:
    sys.path.insert(0, str(SCRIPTS))
    import check_committed_secrets as scanner  # type: ignore[import-not-found]

    for suffix in (".dart", ".plist", ".gradle", ".kts", ".xcconfig", ".json", ".yaml"):
        assert suffix in scanner.COVERED_SUFFIXES, suffix


def test_the_store_release_gate_blocks_rather_than_fails() -> None:
    """Exit 2 means engineering is fine and only external work is outstanding.

    Exit 1 would mean an engineering condition failed, which is the distinction
    that keeps this gate from blocking development.
    """
    result = run_script("store_release_gate.py")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "gate: BLOCKED" in result.stdout
    assert "blocks store submission only" in result.stdout


def test_the_store_identity_gate_invents_no_brand() -> None:
    identity = load(COMPLIANCE / "store-identity.v1.yaml")
    assert identity["gate"] == "BLOCKED_BRAND_IDENTITY"
    for field in identity["fields"].values():
        assert field["status"] == "unresolved"


def _string_values(node: object) -> list[str]:
    """Every string in a parsed document.

    Scans parsed values rather than raw text: comments explaining which words
    are banned necessarily contain those words, and they are not submitted to
    anyone.
    """
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [value for item in node.values() for value in _string_values(item)]
    if isinstance(node, list):
        return [value for item in node for value in _string_values(item)]
    return []


def _affirmative_uses(text: str, term: str) -> list[str]:
    """Occurrences of ``term`` not preceded by a negation.

    A listing must say it does not diagnose or treat anything, which means the
    words appear. Only an affirmative use is a prohibited claim.
    """
    offenders: list[str] = []
    start = 0
    while (index := text.find(term, start)) != -1:
        window = text[max(0, index - 50) : index]
        if not any(negation in window for negation in ("not ", "no ", "never ")):
            offenders.append(text[max(0, index - 50) : index + len(term) + 20])
        start = index + len(term)
    return offenders


def test_store_metadata_makes_no_medical_claim() -> None:
    banned = (
        "treat anxiety",
        "cure insomnia",
        "diagnose",
        "ptsd",
        "clinically proven",
        "medical stress detection",
        "therapy",
        "therapeutic",
    )
    for path in (
        REPO_ROOT / "store" / "apple" / "metadata.en-US.yaml",
        REPO_ROOT / "store" / "google" / "listing.en-US.yaml",
    ):
        # Collapse whitespace: YAML block scalars keep newlines, and a phrase
        # split across two lines is the same phrase to a reader.
        text = " ".join(" ".join(_string_values(load(path))).lower().split())
        for claim in banned:
            offenders = _affirmative_uses(text, claim)
            assert offenders == [], f"{path.name}: {claim}: {offenders}"

        # The required disclaimer must be there, phrased as a denial.
        assert "does not diagnose" in text
        assert "not a substitute for professional care" in text

        # And the approved positioning must actually be present.
        assert "mindfulness" in text
        assert "meditation" in text


def test_reviewer_notes_explain_guest_entry() -> None:
    """Reviewers must be able to evaluate the app with no credentials."""
    for path in (
        REPO_ROOT / "store" / "apple" / "review-notes.md",
        REPO_ROOT / "store" / "google" / "review-notes.md",
    ):
        text = path.read_text(encoding="utf-8").lower()
        assert "no account" in text
        assert "start a session" in text
        assert "delete my meditation data" in text


# --------------------------------------------------------------------------- #
# RG-01..RG-04 — five independent validation axes
# --------------------------------------------------------------------------- #


def _gate_module():
    """Import the gate script as a module."""
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "store_release_gate.py"
    spec = importlib.util.spec_from_file_location("store_release_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["store_release_gate"] = module
    spec.loader.exec_module(module)
    return module


def test_rg01_the_five_axes_are_independently_represented() -> None:
    gate = _gate_module()
    assert gate.AXES == (
        "CI",
        "NATIVE_INTEGRATION",
        "ANDROID_DEVICE",
        "IOS_DEVICE",
        "HUMAN_LISTENING",
    )
    axes = gate.readiness_axes()
    # Five separate values, not one rolled-up verdict.
    assert set(axes) == set(gate.AXES)
    assert len(axes) == 5
    for axis in gate.AXES:
        assert axes[axis] in {gate.PASS, gate.FAIL, gate.NOT_RUN, gate.BLOCKED}
        assert gate.AXIS_MEANING[axis]


def test_rg02_not_run_is_not_pass() -> None:
    """The whole point: an absent result is not a passing one."""
    gate = _gate_module()
    assert gate.NOT_RUN != gate.PASS

    axes = dict.fromkeys(gate.AXES, gate.NOT_RUN)
    axes["CI"] = gate.PASS
    verdicts = gate.readiness_verdicts(axes)
    assert verdicts["STORE_RELEASE_READINESS"] == "BLOCKED"

    # And NOT_RUN blocks exactly as a FAIL does.
    failed = dict.fromkeys(gate.AXES, gate.PASS)
    failed["ANDROID_DEVICE"] = gate.FAIL
    assert gate.readiness_verdicts(failed)["STORE_RELEASE_READINESS"] == "BLOCKED"


def test_rg03_ci_pass_does_not_imply_device_or_listening() -> None:
    """CI covers unit, HTTP, widget, platform-channel and real-SQL tiers.

    None of those is a device, a simulator, or a person listening, so a green
    suite must not move any of the other four axes.
    """
    gate = _gate_module()
    axes = gate.readiness_axes()
    assert axes["CI"] == gate.PASS
    for axis in ("NATIVE_INTEGRATION", "ANDROID_DEVICE", "IOS_DEVICE", "HUMAN_LISTENING"):
        assert axes[axis] == gate.NOT_RUN, axis

    verdicts = gate.readiness_verdicts(axes)
    assert verdicts["CODE_MERGE_READINESS"] == "READY"
    assert verdicts["STORE_RELEASE_READINESS"] == "BLOCKED"


def test_rg04_store_release_needs_every_axis() -> None:
    gate = _gate_module()
    # Only all five passing opens it.
    everything = dict.fromkeys(gate.AXES, gate.PASS)
    assert gate.readiness_verdicts(everything)["STORE_RELEASE_READINESS"] == "READY"

    # Each single omission blocks it on its own.
    for axis in gate.AXES:
        partial = dict.fromkeys(gate.AXES, gate.PASS)
        partial[axis] = gate.NOT_RUN
        assert gate.readiness_verdicts(partial)["STORE_RELEASE_READINESS"] == "BLOCKED", axis


def test_code_merge_and_store_release_are_separate_verdicts() -> None:
    """Merging code and shipping it are different questions.

    Collapsing them is how a green test suite comes to be read as release
    approval, which is the confusion this model exists to prevent.
    """
    gate = _gate_module()
    verdicts = gate.readiness_verdicts(gate.readiness_axes())
    assert set(verdicts) == {"CODE_MERGE_READINESS", "STORE_RELEASE_READINESS"}
    assert verdicts["CODE_MERGE_READINESS"] != verdicts["STORE_RELEASE_READINESS"]


def test_the_gate_reports_axes_in_its_json() -> None:
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "store_release_gate.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=root,
    )
    payload = json.loads(result.stdout)
    assert set(payload["axes"]) == {
        "CI",
        "NATIVE_INTEGRATION",
        "ANDROID_DEVICE",
        "IOS_DEVICE",
        "HUMAN_LISTENING",
    }
    assert payload["verdicts"]["STORE_RELEASE_READINESS"] == "BLOCKED"
    # Still blocked, and still reporting why rather than only that.
    assert payload["gate"] == "BLOCKED"
