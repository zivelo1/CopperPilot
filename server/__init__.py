# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Circuit Design Automation Server
FastAPI-based replacement for N8N workflow
"""

__version__ = "1.0.0"
__author__ = "Circuit Design Automation Team"

from .config import config

# Validate configuration on import
config.validate()