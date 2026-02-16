# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Pytest Configuration and Shared Fixtures
Provides common fixtures for all converter tests
"""

import sys
import shutil
from pathlib import Path
from typing import Generator

import pytest


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def base_output_dir() -> Path:
    """Get the base output directory"""
    return Path("output")


@pytest.fixture(scope="session")
def latest_output_folder(base_output_dir: Path) -> Path:
    """Find the most recent output folder automatically"""
    if not base_output_dir.exists():
        pytest.fail(f"Output directory not found: {base_output_dir}")

    output_dirs = [d for d in base_output_dir.iterdir()
                   if d.is_dir() and d.name != '.DS_Store']

    if not output_dirs:
        pytest.fail("No output directories found")

    latest = sorted(output_dirs, reverse=True)[0]
    print(f"\n📁 Auto-detected: {latest.name}")
    return latest


@pytest.fixture(scope="session")
def lowlevel_dir(latest_output_folder: Path) -> Path:
    """Get the lowlevel directory from latest output"""
    lowlevel = latest_output_folder / "lowlevel"
    if not lowlevel.exists():
        pytest.fail(f"Lowlevel directory not found: {lowlevel}")
    return lowlevel


@pytest.fixture
def kicad_output_dir(latest_output_folder: Path) -> Generator[Path, None, None]:
    """Get KiCad output directory (clean before test)"""
    output_dir = latest_output_folder / "kicad"
    _clean_output_folder(output_dir)
    yield output_dir


@pytest.fixture
def eagle_output_dir(latest_output_folder: Path) -> Generator[Path, None, None]:
    """Get Eagle output directory (clean before test)"""
    output_dir = latest_output_folder / "eagle"
    _clean_output_folder(output_dir)
    yield output_dir


@pytest.fixture
def easyeda_output_dir(latest_output_folder: Path) -> Generator[Path, None, None]:
    """Get EasyEDA Pro output directory (clean before test)"""
    output_dir = latest_output_folder / "easyeda_pro"
    _clean_output_folder(output_dir)
    yield output_dir


@pytest.fixture
def schematics_output_dir(latest_output_folder: Path) -> Generator[Path, None, None]:
    """Get Schematics output directory (clean before test)"""
    output_dir = latest_output_folder / "schematics"
    _clean_output_folder(output_dir)
    yield output_dir


@pytest.fixture
def schematics_desc_output_dir(latest_output_folder: Path) -> Generator[Path, None, None]:
    """Get Schematics Description output directory (clean before test)"""
    output_dir = latest_output_folder / "schematics_text"
    _clean_output_folder(output_dir)
    yield output_dir


@pytest.fixture
def bom_output_dir(latest_output_folder: Path) -> Generator[Path, None, None]:
    """Get BOM output directory (clean before test)"""
    output_dir = latest_output_folder / "bom"
    _clean_output_folder(output_dir)
    yield output_dir


def _clean_output_folder(output_dir: Path) -> None:
    """Remove all files from output folder"""
    print(f"\n🧹 Cleaning {output_dir}...")
    if output_dir.exists():
        for file in output_dir.iterdir():
            if file.is_file():
                file.unlink()
                print(f"  Removed: {file.name}")
            elif file.is_dir() and file.name not in ['ERC', 'DRC', '__pycache__']:
                shutil.rmtree(file)
                print(f"  Removed directory: {file.name}")
    else:
        output_dir.mkdir(parents=True)
    print(f"✅ {output_dir} cleaned")


# Pytest configuration
def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line(
        "markers", "converter: Converter tests (6 tests, ~2 min each)"
    )
    config.addinivalue_line(
        "markers", "validator: Validation tests (varies)"
    )
    config.addinivalue_line(
        "markers", "simulation: Simulation tests (quick, <30s each)"
    )
    config.addinivalue_line(
        "markers", "deep: Deep forensic tests (slow, skip in quick mode)"
    )
    config.addinivalue_line(
        "markers", "integration: Full workflow tests (very slow)"
    )
