# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""KiCad converter utilities."""

from .base import (
    ConversionContext,
    PipelineStage,
    ConversionError,
    ValidationError,
    load_json,
    save_json,
    generate_uuid,
    mm_to_mil,
    mil_to_mm
)

__all__ = [
    'ConversionContext',
    'PipelineStage',
    'ConversionError',
    'ValidationError',
    'load_json',
    'save_json',
    'generate_uuid',
    'mm_to_mil',
    'mil_to_mm'
]