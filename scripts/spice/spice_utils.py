# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
SPICE Utilities — Shared helper functions for SPICE code generation.

V.4 FIX: This module provides canonical sanitization functions used by
BOTH netlist_generator.py and model_library.py, ensuring consistent
name generation across subcircuit definitions and instance references.

Author: CopperPilot Team
Date: February 2026
"""

import re
import sys
from pathlib import Path

# Ensure project root is on sys.path for config import
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from server.config import config


def spice_safe_name(name: str) -> str:
    """
    Canonical SPICE name sanitization — single source of truth.

    Used by BOTH netlist_generator and model_library to ensure subcircuit
    instance references and definitions produce identical names.

    Process:
    1. Transliterate Unicode engineering symbols using config.UNICODE_SANITIZE_MAP
       (e.g., Omega -> Ohm, mu -> u)
    2. Replace spaces with underscores
    3. Strip R-suffix notation (620R -> 620)
    4. Remove all remaining non-ASCII-safe characters (keep A-Z, a-z, 0-9, _, .)

    Args:
        name: Raw name that may contain Unicode characters

    Returns:
        SPICE-safe ASCII name, consistent across all call sites
    """
    s = name
    # Step 1: Transliterate known Unicode engineering symbols
    for unicode_char, ascii_replacement in config.UNICODE_SANITIZE_MAP.items():
        s = s.replace(unicode_char, ascii_replacement)
    # Step 2: Replace spaces
    s = s.replace(' ', '_')
    # Step 3: Strip R-suffix notation (620R -> 620)
    s = re.sub(r'(\d+)[Rr]$', r'\1', s)
    # Step 4: ASCII-safe characters only (SPICE identifiers)
    s = re.sub(r'[^A-Za-z0-9_.]', '_', s)
    return s
