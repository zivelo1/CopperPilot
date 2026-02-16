# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Multi-Agent Circuit Design System

This package provides a hierarchical multi-agent architecture for circuit design.
The system addresses the fundamental limitation of single-agent approaches:
context overload when designing complex circuits with 200+ components.

Architecture:
    DesignSupervisor
        └── ModuleAgent (per module)
                ├── ComponentAgent (component selection)
                ├── ConnectionAgent (connection synthesis)
                └── ValidationAgent (per-module validation)
        └── IntegrationAgent (cross-module integration)

Author: CopperPilot Team
Date: January 2026
Version: 1.0
"""

from .design_supervisor import DesignSupervisor
from .module_agent import ModuleAgent
from .component_agent import ComponentAgent
from .connection_agent import ConnectionAgent
from .validation_agent import ValidationAgent
from .integration_agent import IntegrationAgent

__all__ = [
    'DesignSupervisor',
    'ModuleAgent',
    'ComponentAgent',
    'ConnectionAgent',
    'ValidationAgent',
    'IntegrationAgent'
]
