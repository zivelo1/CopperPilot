#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Deep Schematics (PNG) Validation — Coverage + Structural Parity

Purpose
-------
Validate that for every lowlevel circuit JSON, a corresponding schematic PNG
exists and is non-trivial, and that the drawing is consistent with the textual
schematics description (wiring) and lowlevel metadata.

What is checked (generic, tool-agnostic):
- Coverage: one PNG per lowlevel circuit
- Size: PNGs must be non-tiny (> 1KB)
- Naming: consistent slug mapping from circuit name → file name
- Structural parity (lightweight):
  • Component reference set in schematics_desc equals lowlevel references
  • Optional: presence of key net names from lowlevel in schematics_desc text

Notes
-----
- This validator deliberately avoids pixel or OCR checks.
- If a future sidecar manifest (JSON/DOT) is emitted alongside PNGs, extend
  this script to compare the manifest graph to the lowlevel graph directly.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


def _find_latest_output_dir(root: Path) -> Path | None:
    out = root / "output"
    if not out.exists():
        return None
    dirs = [p for p in out.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _slugify_module_name(stem: str) -> str:
    """Create a hyphenated slug used by PNG filenames.

    - Drop leading 'circuit_'
    - Lowercase
    - Replace spaces/underscores/dots with '-'
    - Remove any char that's not alnum or '-'
    - Collapse multiple '-' into one
    """
    name = stem
    if name.startswith("circuit_"):
        name = name[len("circuit_"):]
    name = name.lower()
    name = re.sub(r"[\s_.]+", "-", name)
    name = re.sub(r"[^a-z0-9-]", "", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name


def _desc_path_candidates(desc_dir: Path, stem: str) -> List[Path]:
    """Return plausible schematics_desc paths for a given lowlevel stem.

    Accept both underscore and dotted variants observed in outputs.
    """
    name = stem
    if name.startswith("circuit_"):
        name = name[len("circuit_"):]
    candidates = [
        desc_dir / f"circuit_{name}_wiring.txt",
        desc_dir / f"circuit_{name.replace('-', '_')}_wiring.txt",
        desc_dir / f"circuit_{name.replace('_', '.')}_wiring.txt",
    ]
    # Deduplicate while preserving order
    seen: Set[Path] = set()
    unique: List[Path] = []
    for p in candidates:
        if p not in seen:
            unique.append(p)
            seen.add(p)
    return unique


def _parse_lowlevel_refs(low_file: Path) -> Set[str]:
    """Extract component references from a lowlevel circuit JSON."""
    try:
        data = json.loads(low_file.read_text(encoding="utf-8"))
        comps = data.get("circuit", {}).get("components", [])
        return {str(c.get("ref", "")).strip() for c in comps if c.get("ref")}
    except Exception:
        return set()


def _parse_lowlevel_key_nets(low_file: Path) -> Set[str]:
    """Extract a small set of 'key' nets to look for in description text.

    We keep this conservative: power rails and named nets (exclude NET_*, NC_*, and _NC).
    """
    try:
        data = json.loads(low_file.read_text(encoding="utf-8"))
        nets = set(data.get("circuit", {}).get("nets", []) or [])
        nets = {n for n in nets 
                if n and not n.startswith("NET_") 
                and not n.upper().startswith("NC_") 
                and not n.upper().endswith("_NC")}
        # Focus on a small subset to avoid false negatives
        focus = {n for n in nets if any(k in n for k in ("GND", "VCC", "VDD", "POWER", "LOGIC", "OUT", "SENSE"))}
        # Always include bare GND if present
        if "GND" in nets:
            focus.add("GND")
        return focus
    except Exception:
        return set()


def _parse_desc_components(desc_file: Path) -> Set[str]:
    """Parse component references from the schematics_desc COMPONENT LIST section.

    Matches lines like: '  R1: 10k', '  U1: IR2110', etc., across all categories.
    """
    text = desc_file.read_text(encoding="utf-8", errors="ignore")
    refs: Set[str] = set()
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z]+\d+):\s", line)
        if m:
            refs.add(m.group(1))
    return refs


def _desc_contains_key_nets(desc_file: Path, nets: Set[str]) -> Set[str]:
    """Return the subset of 'key' nets found verbatim in the description text."""
    if not nets:
        return set()
    text = desc_file.read_text(encoding="utf-8", errors="ignore")
    found = {n for n in nets if n in text}
    return found


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    latest = _find_latest_output_dir(repo)
    if not latest:
        print("ERROR: No output/* directory found")
        return 1

    low = latest / "lowlevel"
    sch = latest / "schematics"
    desc = latest / "schematics_desc"
    if not low.exists() or not sch.exists():
        print(f"ERROR: Missing required folders (lowlevel={low.exists()} schematics={sch.exists()})")
        return 1

    # Expected images based on lowlevel circuits
    circuits = [p for p in low.glob("circuit_*.json")]
    missing_png: List[str] = []
    tiny_png: List[str] = []
    struct_errors: List[str] = []
    struct_warnings: List[str] = []

    for low_file in circuits:
        stem = low_file.stem  # e.g., circuit_power_supply_module
        slug = _slugify_module_name(stem)
        png = sch / f"circuit-{slug}.png"

        # Coverage and size checks
        if not png.exists():
            missing_png.append(png.name)
        elif png.stat().st_size < 1024:
            tiny_png.append(png.name)

        # Structural parity: compare schematics_desc vs lowlevel component refs
        if desc.exists():
            desc_paths = _desc_path_candidates(desc, stem)
            desc_file = next((p for p in desc_paths if p.exists()), None)
            if not desc_file:
                struct_errors.append(f"No schematics_desc found for {stem} (tried: {', '.join(p.name for p in desc_paths)})")
            else:
                low_refs = _parse_lowlevel_refs(low_file)
                desc_refs = _parse_desc_components(desc_file)
                if not low_refs:
                    struct_errors.append(f"{stem}: could not parse lowlevel component refs")
                elif not desc_refs:
                    struct_errors.append(f"{stem}: could not parse schematics_desc component refs ({desc_file.name})")
                else:
                    if low_refs != desc_refs:
                        only_low = sorted(low_refs - desc_refs)
                        only_desc = sorted(desc_refs - low_refs)
                        msg = [f"{stem}: component ref mismatch"]
                        if only_low:
                            msg.append(f"  in lowlevel only: {', '.join(only_low)}")
                        if only_desc:
                            msg.append(f"  in schematics_desc only: {', '.join(only_desc)}")
                        struct_errors.append("\n".join(msg))

                # Optional: key net presence heuristic in description
                key_nets = _parse_lowlevel_key_nets(low_file)
                if key_nets:
                    found = _desc_contains_key_nets(desc_file, key_nets)
                    missing_keys = sorted(key_nets - found)
                    if missing_keys:
                        struct_warnings.append(f"{stem}: key nets not mentioned in schematics_desc: {', '.join(missing_keys)}")

    # Reporting
    failed = False
    if missing_png:
        failed = True
        print("Missing PNGs:")
        for f in missing_png:
            print(f"  - {f}")
    if tiny_png:
        failed = True
        print("Tiny PNGs (<1KB):")
        for f in tiny_png:
            print(f"  - {f}")
    if struct_errors:
        failed = True
        print("Structural parity issues:")
        for msg in struct_errors:
            print(f"  - {msg}")
    if struct_warnings:
        print("Structural parity warnings:")
        for msg in struct_warnings:
            print(f"  - {msg}")

    if failed:
        return 1

    print("Schematics (PNG) deep validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
