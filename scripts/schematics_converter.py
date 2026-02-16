#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Schematic Generator - Modular Architecture
Version: 2.0
Date: January 2025

Generates professional electronic schematic diagrams from JSON circuit files.
Produces high-resolution PNG images with complete component connectivity.
"""

import sys
import json
import time
import re
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

# Import schematic modules
from schematics.modules import (
    SchematicContext,
    InputProcessor,
    LayoutEngine,
    WireRouter,
    Renderer,
    Validator
)


def slugify_module_name(stem: str) -> str:
    """
    Create a hyphenated slug for PNG filenames - MUST match validator logic.

    This function is GENERIC and ensures consistency between PNG generation
    and validation across all circuit types.

    Transformation rules:
    - Drop leading 'circuit_'
    - Lowercase
    - Replace spaces/underscores/dots with '-'
    - Remove any char that's not alnum or '-'
    - Collapse multiple '-' into one

    Examples:
        'circuit_channel_2_module_1.5mhz' -> 'channel-2-module-1-5mhz'
        'circuit_power_supply_module' -> 'power-supply-module'
        'CIRCUIT_Main_Controller_v2.1' -> 'main-controller-v2-1'

    Args:
        stem: Circuit file stem (without extension)

    Returns:
        Slugified name for use in PNG filename
    """
    name = stem
    name = name.lower()
    # CRITICAL: Replace spaces, underscores, AND DOTS with hyphens
    name = re.sub(r"[\s_.]+", "-", name)
    # Remove non-alphanumeric/hyphen characters
    name = re.sub(r"[^a-z0-9-]", "", name)
    # Collapse multiple hyphens
    name = re.sub(r"-+", "-", name).strip("-")
    
    # Ensure it starts with circuit-
    if not name.startswith("circuit-"):
        name = f"circuit-{name}"
        
    return name


class SchematicConverter:
    """Main orchestrator for schematic generation pipeline."""

    def __init__(self, input_path: str, output_path: str):
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.config = self._load_config()
        self.stats = {
            'start_time': time.time(),
            'circuits_processed': 0,
            'circuits_success': 0,
            'circuits_failed': 0,
            'total_components': 0,
            'total_nets': 0
        }
        # File-based error logger — persists errors to disk for post-mortem analysis
        self._error_logger = self._setup_error_logger()

    def _load_config(self) -> Dict:
        """Load configuration settings."""
        config_file = Path(__file__).parent / 'schematics' / 'config' / 'settings.json'
        if config_file.exists():
            with open(config_file, 'r') as f:
                return json.load(f)

        # Default configuration
        return {
            'canvas': {
                'width': 3600,
                'height': 2400,
                'dpi': 300,
                'grid_size': 10
            },
            'layout': {
                'component_spacing_x': 350,
                'component_spacing_y': 280,
                'margin': 100
            },
            'routing': {
                'wire_width': 2,
                'power_wire_width': 3,
                'wire_spacing': 10
            },
            'rendering': {
                'background_color': 'white',
                'grid_color': '#f0f0f0',
                'high_quality': True
            }
        }

    def _setup_error_logger(self) -> logging.Logger:
        """
        Create a file-based logger that writes errors to the output directory.
        Returns a dedicated logger instance for persistent error tracking.
        """
        self.output_path.mkdir(parents=True, exist_ok=True)
        error_log = logging.getLogger(f'schematics_converter.{id(self)}')
        error_log.setLevel(logging.DEBUG)
        # Avoid duplicate handlers on re-initialization
        if not error_log.handlers:
            handler = logging.FileHandler(
                self.output_path / 'schematics_errors.log', mode='w'
            )
            handler.setFormatter(
                logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
            )
            error_log.addHandler(handler)
        return error_log

    def convert(self) -> bool:
        """Main conversion method."""
        print("\n" + "="*60)
        print("SCHEMATIC GENERATOR - MODULAR ARCHITECTURE v2.0")
        print("="*60)
        print(f"Input: {self.input_path}")
        print(f"Output: {self.output_path}")
        print("="*60)

        # Create output directory
        self.output_path.mkdir(parents=True, exist_ok=True)

        # Process all circuit files
        if self.input_path.is_file():
            # Single file
            circuit_files = [self.input_path]
        else:
            # Directory of files - check both uppercase and lowercase
            circuit_files = list(self.input_path.glob('circuit_*.json'))
            if not circuit_files:
                circuit_files = list(self.input_path.glob('CIRCUIT_*.json'))
            # DO NOT process design.json - it's a summary, not individual circuits

        if not circuit_files:
            print("❌ No circuit files found")
            return False

        print(f"\nFound {len(circuit_files)} circuit file(s) to process\n")

        all_success = True
        for circuit_file in circuit_files:
            # GENERIC slugification - MUST match validator logic for consistency
            circuit_name = slugify_module_name(circuit_file.stem)
            print(f"\nProcessing: {circuit_name}")
            print("-" * 40)

            success = self._process_single_circuit(circuit_file, circuit_name)

            if success:
                self.stats['circuits_success'] += 1
                print(f"✅ {circuit_name}: Schematic generated successfully")
            else:
                self.stats['circuits_failed'] += 1
                all_success = False
                print(f"❌ {circuit_name}: Schematic generation failed")

            self.stats['circuits_processed'] += 1

        # Print final statistics
        self._print_statistics()

        return all_success

    def _process_single_circuit(self, circuit_file: Path, circuit_name: str) -> bool:
        """Process a single circuit file through the pipeline."""
        try:
            # Log circuit file size for large-circuit diagnostics
            file_size_kb = circuit_file.stat().st_size / 1024
            self._error_logger.info(
                f"Processing {circuit_name}: {file_size_kb:.1f} KB"
            )

            # Initialize context
            context = SchematicContext()
            context.input_path = circuit_file
            context.output_path = self.output_path / f"{circuit_name}.png"

            # Apply configuration
            if 'canvas' in self.config:
                context.canvas_width = self.config['canvas']['width']
                context.canvas_height = self.config['canvas']['height']
            if 'layout' in self.config:
                context.component_spacing_x = self.config['layout']['component_spacing_x']
                context.component_spacing_y = self.config['layout']['component_spacing_y']

            # Create pipeline stages
            pipeline = [
                InputProcessor(self.config),
                LayoutEngine(self.config),
                WireRouter(self.config),
                Renderer(self.config),
                Validator(self.config)
            ]

            # Execute pipeline with per-stage timing
            for stage in pipeline:
                stage_name = stage.__class__.__name__
                stage_start = time.time()
                try:
                    context = stage.execute(context)
                    stage_elapsed = time.time() - stage_start
                    self._error_logger.info(
                        f"  {circuit_name} | {stage_name}: {stage_elapsed:.2f}s"
                    )

                    # Check for critical errors
                    if context.errors and isinstance(stage, Validator):
                        print(f"\nValidation errors detected:")
                        for error in context.errors[:5]:
                            print(f"  - {error}")
                        if len(context.errors) > 5:
                            print(f"  ... and {len(context.errors) - 5} more errors")
                        self._error_logger.warning(
                            f"  {circuit_name} | Validation: "
                            f"{len(context.errors)} error(s)"
                        )

                except Exception as e:
                    stage_elapsed = time.time() - stage_start
                    error_msg = (
                        f"{circuit_name} | {stage_name} FAILED after "
                        f"{stage_elapsed:.2f}s: {e}"
                    )
                    print(f"\nStage {stage_name} failed: {e}")
                    self._error_logger.error(error_msg, exc_info=True)
                    return False

            # Save the image
            if context.image:
                renderer = Renderer(self.config)
                renderer.save_image(context)

                # Update global statistics
                comp_count = len(context.components)
                net_count = len(context.nets)
                self.stats['total_components'] += comp_count
                self.stats['total_nets'] += net_count

                self._error_logger.info(
                    f"  {circuit_name} | SUCCESS: "
                    f"{comp_count} components, {net_count} nets"
                )

                # Generate validation report
                validator = Validator(self.config)
                report = validator.generate_report(context)

                return True
            else:
                msg = f"No image generated for {circuit_name}"
                print(f"{msg}")
                self._error_logger.error(msg)
                return False

        except Exception as e:
            error_msg = f"Unexpected error processing {circuit_name}: {e}"
            print(f"\n{error_msg}")
            self._error_logger.error(error_msg, exc_info=True)
            return False

    def _print_statistics(self):
        """Print final conversion statistics."""
        elapsed = time.time() - self.stats['start_time']

        print("\n" + "="*60)
        print("CONVERSION COMPLETE")
        print("="*60)
        print(f"Circuits processed: {self.stats['circuits_processed']}")
        print(f"  Successful: {self.stats['circuits_success']}")
        print(f"  Failed: {self.stats['circuits_failed']}")
        print(f"Total components: {self.stats['total_components']}")
        print(f"Total nets: {self.stats['total_nets']}")
        print(f"Time elapsed: {elapsed:.2f} seconds")

        if self.stats['circuits_failed'] == 0:
            print("\n✅ ALL SCHEMATICS GENERATED SUCCESSFULLY")
        else:
            print(f"\n⚠️  {self.stats['circuits_failed']} CIRCUIT(S) FAILED")

        print("="*60)
        print(f"\nOutput files saved to: {self.output_path}")
        print("Files generated:")
        print("  - *.png (Schematic diagrams)")

def main():
    """Main entry point."""
    if len(sys.argv) != 3:
        print("Usage: python3 schematics_converter.py <input_folder> <output_folder>")
        print("\nExamples:")
        print("  python3 schematics_converter.py lowlevel/ schematics/")
        print("  python3 schematics_converter.py circuits/CIRCUIT_Power.json schematics/")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    # Check input exists
    if not Path(input_path).exists():
        print(f"❌ Error: Input path '{input_path}' does not exist")
        sys.exit(1)

    # Run converter
    converter = SchematicConverter(input_path, output_path)
    success = converter.convert()

    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()