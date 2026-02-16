#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Clean up KiCad output folders by moving files to correct locations.

PHASE -1 (2025-11-23): File Organization (ORG-5)
Moves misplaced files from flat kicad/ folder to organized subfolders.

GENERIC: Works for any kicad output folder, any circuit count.

Usage:
    python3 scripts/utils/cleanup_kicad_output.py output/UNIQUE/kicad/
"""

import shutil
import sys
from pathlib import Path


def cleanup_kicad_folder(kicad_dir: Path) -> dict:
    """
    Move misplaced files to correct folders.

    Args:
        kicad_dir: Path to kicad output directory

    Returns:
        Dictionary with counts of files moved per type
    """
    if not kicad_dir.exists():
        print(f"❌ Error: Directory not found: {kicad_dir}")
        return {}

    # Create organized subdirectories
    (kicad_dir / "routing").mkdir(exist_ok=True)
    (kicad_dir / "quality").mkdir(exist_ok=True)

    # Create log directories at PROJECT ROOT
    project_root = kicad_dir.parent.parent.parent  # output/UNIQUE/kicad -> project root
    log_dir = project_root / "logs" / "kicad" / "freerouting"
    log_dir.mkdir(parents=True, exist_ok=True)

    counts = {
        'dsn': 0,
        'ses': 0,
        'failed': 0,
        'passed': 0,
        'logs': 0
    }

    print(f"🧹 Cleaning up: {kicad_dir}")
    print()

    # Move .dsn and .ses files to routing/
    for ext in ['.dsn', '.ses']:
        for file in kicad_dir.glob(f"*{ext}"):
            target = kicad_dir / "routing" / file.name
            print(f"  📦 {file.name} → routing/")
            shutil.move(str(file), str(target))
            counts['dsn' if ext == '.dsn' else 'ses'] += 1

    # Move .FAILED and .PASSED files to quality/
    for ext in ['.FAILED', '.PASSED']:
        for file in kicad_dir.glob(f"*{ext}"):
            target = kicad_dir / "quality" / file.name
            print(f"  🏷️  {file.name} → quality/")
            shutil.move(str(file), str(target))
            counts['failed' if ext == '.FAILED' else 'passed'] += 1

    # Move .log files to logs/kicad/freerouting/
    for file in kicad_dir.glob("*.freerouting.log"):
        target = log_dir / file.name
        print(f"  📝 {file.name} → logs/kicad/freerouting/")
        shutil.move(str(file), str(target))
        counts['logs'] += 1

    # Clean up empty test_results folder if it exists
    test_results = kicad_dir / "test_results"
    if test_results.exists() and test_results.is_dir():
        try:
            # Move any marker files to quality/
            for failed_file in test_results.glob("*.FAILED"):
                target = kicad_dir / "quality" / failed_file.name
                print(f"  🏷️  test_results/{failed_file.name} → quality/")
                shutil.move(str(failed_file), str(target))
                counts['failed'] += 1

            # Remove empty test_results folder
            if not any(test_results.iterdir()):
                test_results.rmdir()
                print(f"  🗑️  Removed empty test_results/ folder")
        except Exception as e:
            print(f"  ⚠️  Could not clean test_results/: {e}")

    print()
    print("=" * 60)
    print("✅ Cleanup complete!")
    print()
    print(f"Files moved:")
    print(f"  • DSN files: {counts['dsn']}")
    print(f"  • SES files: {counts['ses']}")
    print(f"  • FAILED markers: {counts['failed']}")
    print(f"  • PASSED markers: {counts['passed']}")
    print(f"  • Freerouting logs: {counts['logs']}")
    print(f"  • Total: {sum(counts.values())} files")
    print()
    print("Organized folder structure:")
    print(f"  • output/kicad/routing/     - DSN/SES routing artifacts")
    print(f"  • output/kicad/quality/     - FAILED/PASSED quality markers")
    print(f"  • logs/kicad/freerouting/   - Freerouting execution logs")
    print("=" * 60)

    return counts


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python3 cleanup_kicad_output.py output/UNIQUE/kicad/")
        print()
        print("Example:")
        print("  python3 scripts/utils/cleanup_kicad_output.py output/20251111-080123-2750d963/kicad/")
        sys.exit(1)

    kicad_dir = Path(sys.argv[1])
    cleanup_kicad_folder(kicad_dir)


if __name__ == "__main__":
    main()
