#!/usr/bin/env python3
"""Generate the bell tones from first principles.

Provenance is the point. These files are synthesised here, from arithmetic in
this script, and are therefore unambiguously the project's own work: there is no
sample, no recording and no third-party asset anywhere in the chain. The
alternative - downloading a "free" bell from a sample site - carries licensing
that ranges from clear to fictional, and store review is the wrong place to
discover which.

A struck bell is a set of inharmonic partials decaying at different rates, the
higher ones faster. That is what this models: a small partial series over a
fundamental, each with its own exponential decay, summed and windowed. It is not
a recording of a real singing bowl and does not claim to be.

Regenerating is deterministic: same script, same bytes, same sha256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 44_100
BIT_DEPTH = 16
CHANNELS = 1

REPO_ROOT = Path(__file__).resolve().parent.parent
# Inside the Flutter package, because Flutter can only bundle assets that live
# under the package root. Program004 generated these at the repository root and
# never declared them in pubspec.yaml, so they could not reach a device.
ASSET_ROOT = REPO_ROOT / "apps" / "mobile" / "assets" / "audio"
BELL_DIR = ASSET_ROOT / "bells"
MANIFEST = ASSET_ROOT / "PROVENANCE.json"


@dataclass(frozen=True, slots=True)
class Bell:
    name: str
    fundamental_hz: float
    duration_s: float
    partials: tuple[tuple[float, float, float], ...]
    """(frequency ratio, amplitude, decay seconds) per partial."""
    purpose: str


# Ratios are inharmonic on purpose. A harmonic series sounds like an organ; a
# struck metal bell does not, and the minor-third partial is most of why a bowl
# sounds like a bowl.
BELLS = (
    Bell(
        name="opening",
        fundamental_hz=220.0,
        duration_s=2.0,
        partials=(
            (1.0, 1.00, 1.9),
            (2.0, 0.35, 1.2),
            (2.4, 0.28, 0.9),
            (3.0, 0.18, 0.6),
            (5.4, 0.09, 0.35),
        ),
        purpose="Marks the start of a session.",
    ),
    Bell(
        name="closing",
        fundamental_hz=174.61,
        duration_s=2.0,
        partials=(
            (1.0, 1.00, 2.0),
            (2.0, 0.30, 1.3),
            (2.4, 0.24, 1.0),
            (3.0, 0.14, 0.7),
            (5.4, 0.07, 0.4),
        ),
        purpose="Marks the end of a session. Lower and longer than the opening.",
    ),
    Bell(
        name="transition",
        fundamental_hz=261.63,
        duration_s=1.2,
        partials=(
            (1.0, 1.00, 1.1),
            (2.0, 0.22, 0.7),
            (2.4, 0.16, 0.5),
        ),
        purpose="Optional marker between stages. Quieter and shorter.",
    ),
)

# A 15 ms fade at each end. Without it the first and last samples are a step
# change, which is heard as a click - the one artefact guaranteed to pull
# somebody out of a meditation.
FADE_MS = 15
PEAK = 0.72
"""Headroom below full scale, so a bell never clips on a device that applies
its own gain."""


def synthesize(bell: Bell) -> bytes:
    total = int(SAMPLE_RATE * bell.duration_s)
    fade = int(SAMPLE_RATE * FADE_MS / 1000)
    normalizer = sum(amplitude for _, amplitude, _ in bell.partials)

    frames = bytearray()
    for index in range(total):
        t = index / SAMPLE_RATE
        value = 0.0
        for ratio, amplitude, decay_s in bell.partials:
            value += amplitude * math.sin(2 * math.pi * bell.fundamental_hz * ratio * t) * math.exp(
                -t / decay_s
            )
        value /= normalizer

        if index < fade:
            value *= index / fade
        remaining = total - index
        if remaining < fade:
            value *= remaining / fade

        sample = int(max(-1.0, min(1.0, value * PEAK)) * 32767)
        frames += struct.pack("<h", sample)
    return bytes(frames)


def write_wav(path: Path, frames: bytes) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(BIT_DEPTH // 8)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames)


def build(check_only: bool = False) -> int:
    BELL_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    stale: list[str] = []

    for bell in BELLS:
        frames = synthesize(bell)
        path = BELL_DIR / f"{bell.name}.wav"
        if check_only or path.exists():
            expected = hashlib.sha256(frames).hexdigest()
            if not path.exists():
                stale.append(f"{path.name}: missing")
            else:
                with wave.open(str(path), "rb") as handle:
                    actual_frames = handle.readframes(handle.getnframes())
                if hashlib.sha256(actual_frames).hexdigest() != expected:
                    stale.append(f"{path.name}: content differs from the generator")
        if not check_only:
            write_wav(path, frames)

        entries.append(
            {
                "file": f"apps/mobile/assets/audio/bells/{bell.name}.wav",
                "flutter_asset": f"assets/audio/bells/{bell.name}.wav",
                "asset_key": f"bell.{bell.name}",
                "purpose": bell.purpose,
                "origin": "generated",
                "generator": "scripts/generate_bells.py",
                "license": "Project-owned. Synthesised from arithmetic in the generator.",
                "third_party_content": False,
                "sample_rate_hz": SAMPLE_RATE,
                "channels": CHANNELS,
                "bit_depth": BIT_DEPTH,
                "duration_ms": round(bell.duration_s * 1000),
                "sha256": hashlib.sha256(frames).hexdigest(),
            }
        )

    manifest = {
        "note": (
            "Every audio asset shipped with this app is listed here with its "
            "origin. Nothing is imported from a third party. An asset without "
            "an entry in this file fails the provenance test. flutter_asset "
            "is the key the app loads it by; file is the repository path."
        ),
        "assets": entries,
    }

    if check_only:
        if stale:
            for line in stale:
                print(f"stale: {line}")
            return 1
        if not MANIFEST.exists():
            print("stale: PROVENANCE.json missing")
            return 1
        if json.loads(MANIFEST.read_text()) != manifest:
            print("stale: PROVENANCE.json does not match the generator")
            return 1
        print("bell assets and provenance are current")
        return 0

    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(entries)} bells and {MANIFEST.relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify without writing, for CI"
    )
    return build(check_only=parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
