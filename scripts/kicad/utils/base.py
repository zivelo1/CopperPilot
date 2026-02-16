# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Base classes and utilities for KiCad converter modules."""

import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class ConversionContext:
    """Context object passed through the conversion pipeline."""
    input_path: Path
    output_path: Path
    input_data: Dict[str, Any] = field(default_factory=dict)
    components: Dict[str, Any] = field(default_factory=dict)
    symbols: Dict[str, Any] = field(default_factory=dict)
    footprints: Dict[str, Any] = field(default_factory=dict)
    layout: Dict[str, Any] = field(default_factory=dict)
    netlist: Dict[str, Any] = field(default_factory=dict)
    routes: Dict[str, Any] = field(default_factory=dict)
    schematic: Dict[str, Any] = field(default_factory=dict)
    pcb: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)

class PipelineStage(ABC):
    """Abstract base class for pipeline stages."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def process(self, context: ConversionContext) -> ConversionContext:
        """Process the context and return modified context."""
        pass

    def validate_input(self, context: ConversionContext) -> bool:
        """Validate input before processing."""
        return True

    def handle_error(self, error: Exception, context: ConversionContext) -> ConversionContext:
        """Handle errors during processing."""
        error_msg = f"{self.__class__.__name__}: {str(error)}"
        self.logger.error(error_msg)
        context.errors.append(error_msg)
        return context

class ConversionError(Exception):
    """Custom exception for conversion errors."""
    pass

class ValidationError(ConversionError):
    """Exception for validation errors."""
    pass

def load_json(filepath: Path) -> Dict[str, Any]:
    """Load JSON file with error handling."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {filepath}: {e}")
        raise ConversionError(f"Failed to load {filepath}: {e}")

def save_json(data: Dict[str, Any], filepath: Path) -> None:
    """Save data to JSON file."""
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")
        raise ConversionError(f"Failed to save {filepath}: {e}")

def generate_uuid() -> str:
    """Generate a UUID for KiCad elements."""
    import uuid
    return str(uuid.uuid4())

def mm_to_mil(mm: float) -> int:
    """Convert millimeters to mils."""
    return int(mm * 39.3701)

def mil_to_mm(mil: int) -> float:
    """Convert mils to millimeters."""
    return mil / 39.3701