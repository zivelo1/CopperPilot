# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Converter Runner Module
Manages execution of all converter scripts
"""
import subprocess
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
import asyncio
import concurrent.futures

from server.config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ConverterRunner:
    """
    Runs all converter scripts to transform lowlevel JSON to various formats.

    Fix G.10: Checks KiCad CLI availability at init and logs a clear warning
    when ERC/DRC validation will be limited to structural checks only.
    """

    # =========================================================================
    # CONVERTER DEFINITIONS
    # Each converter transforms lowlevel JSON to a specific output format.
    # The SPICE converter was added in December 2025 for circuit simulation.
    # =========================================================================
    CONVERTERS = {
        'kicad': {
            'script': 'kicad_converter.py',
            'output_folder': 'kicad',
            'extensions': ['.kicad_pro', '.kicad_sch', '.kicad_pcb'],
            'description': 'KiCad EDA format'
        },
        'eagle': {
            'script': 'eagle_converter.py',
            'output_folder': 'eagle',
            'extensions': ['.sch', '.brd'],
            'description': 'Autodesk Eagle format'
        },
        'easyeda_pro': {
            'script': 'easyeda_converter_pro.py',
            'output_folder': 'easyeda_pro',
            'extensions': ['.epro'],
            'description': 'EasyEDA Professional format'
        },
        'schematics': {
            'script': 'schematics_converter.py',
            'output_folder': 'schematics',
            'extensions': ['.png'],
            'description': 'PNG schematic diagrams'
        },
        'schematics_text': {
            'script': 'schematics_text_converter.py',
            'output_folder': 'schematics_desc',
            'extensions': ['.txt'],
            'description': 'Human-readable wiring instructions'
        },
        'bom': {
            'script': 'bom_converter.py',
            'output_folder': 'bom',
            'extensions': ['.csv', '.html', '.json'],
            'description': 'Bill of Materials'
        },
        # SPICE/LTSpice converter - Added December 2025
        # Generates simulation netlists for behavioral validation
        'spice': {
            'script': 'spice_converter.py',
            'output_folder': 'spice',
            'extensions': ['.cir', '.asc'],
            'description': 'SPICE/LTSpice simulation files'
        }
    }

    def __init__(self, project_folder: str):
        """
        Initialize converter runner

        Args:
            project_folder: Name of project folder in output directory
        """
        self.project_folder = project_folder
        self.project_path = config.OUTPUT_DIR / project_folder
        self.lowlevel_dir = self.project_path / "lowlevel"

        if not self.lowlevel_dir.exists():
            raise FileNotFoundError(f"Lowlevel directory not found: {self.lowlevel_dir}")

        logger.info(f"Converter runner initialized for project: {project_folder}")

        # Fix G.10: Check KiCad CLI availability at startup
        kicad_cli_path = Path(config.KICAD_CONFIG.get("kicad_cli_path", ""))
        if not kicad_cli_path.exists():
            logger.warning(
                f"KiCad CLI not found at '{kicad_cli_path}'. "
                f"KiCad ERC/DRC results will be UNVALIDATED (structural checks only). "
                f"Install KiCad 9 or set KICAD_CLI_PATH env var for full validation."
            )

    def run_converter(self, format_type: str) -> Dict:
        """
        Run a specific converter

        Args:
            format_type: Type of converter to run (kicad, eagle, etc.)

        Returns:
            Dict with conversion results
        """
        if format_type not in self.CONVERTERS:
            return {
                'success': False,
                'format': format_type,
                'error': f"Unknown converter type: {format_type}"
            }

        converter_info = self.CONVERTERS[format_type]
        script_path = config.SCRIPTS_DIR / converter_info['script']

        if not script_path.exists():
            return {
                'success': False,
                'format': format_type,
                'error': f"Converter script not found: {script_path}"
            }

        output_dir = self.project_path / converter_info['output_folder']
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Running {format_type} converter...")

        try:
            # Prepare command
            # Special handling for BOM converter which uses components.csv and -o flag
            if format_type == 'bom':
                components_csv = self.lowlevel_dir / "components.csv"
                if not components_csv.exists():
                    logger.error(f"components.csv not found in {self.lowlevel_dir}")
                    return {
                        'success': False,
                        'format': format_type,
                        'error': f"components.csv not found in lowlevel directory"
                    }
                # FIXED: Use current Python interpreter (venv Python)
                # This ensures all dependencies are available
                cmd = [
                    sys.executable,  # Use venv Python, not system python3
                    str(script_path),
                    str(components_csv),  # Pass the CSV file, not the directory
                    '-o',
                    str(output_dir)
                ]
            else:
                # FIXED: Use current Python interpreter (venv Python)
                # This ensures all dependencies are available
                cmd = [
                    sys.executable,  # Use venv Python, not system python3
                    str(script_path),
                    str(self.lowlevel_dir),
                    str(output_dir)
                ]

            # Run converter with cwd=project root so all imports resolve
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,  # 60 second timeout
                cwd=str(config.BASE_DIR)
            )

            # Check result
            if result.returncode != 0:
                logger.error(f"{format_type} converter failed: {result.stderr}")
                return {
                    'success': False,
                    'format': format_type,
                    'error': result.stderr,
                    'output': result.stdout
                }

            # List generated files
            generated_files = []
            for ext in converter_info['extensions']:
                generated_files.extend(list(output_dir.glob(f"*{ext}")))

            logger.info(f"{format_type} converter completed: {len(generated_files)} files generated")

            return {
                'success': True,
                'format': format_type,
                'output_dir': str(output_dir),
                'files': [f.name for f in generated_files],
                'count': len(generated_files),
                'output': result.stdout
            }

        except subprocess.TimeoutExpired:
            logger.error(f"{format_type} converter timed out")
            return {
                'success': False,
                'format': format_type,
                'error': "Converter timed out after 60 seconds"
            }
        except Exception as e:
            logger.error(f"Error running {format_type} converter: {e}")
            return {
                'success': False,
                'format': format_type,
                'error': str(e)
            }

    def run_all_converters(self, parallel: bool = True) -> Dict:
        """
        Run all converters

        Args:
            parallel: If True, run converters in parallel

        Returns:
            Dict with results for all converters
        """
        logger.info(f"Running all converters (parallel={parallel})...")

        results = {}

        if parallel:
            # Run converters in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(self.run_converter, format_type): format_type
                    for format_type in self.CONVERTERS.keys()
                }

                for future in concurrent.futures.as_completed(futures):
                    format_type = futures[future]
                    try:
                        result = future.result()
                        results[format_type] = result
                    except Exception as e:
                        logger.error(f"Error in parallel conversion for {format_type}: {e}")
                        results[format_type] = {
                            'success': False,
                            'format': format_type,
                            'error': str(e)
                        }
        else:
            # Run converters sequentially
            for format_type in self.CONVERTERS.keys():
                results[format_type] = self.run_converter(format_type)

        # Summary
        successful = sum(1 for r in results.values() if r.get('success'))
        failed = len(results) - successful

        logger.info(f"Conversion complete: {successful} successful, {failed} failed")

        return {
            'summary': {
                'total': len(results),
                'successful': successful,
                'failed': failed
            },
            'results': results
        }

    async def run_all_converters_async(self) -> Dict:
        """
        Run all converters asynchronously
        """
        logger.info("Running all converters asynchronously...")

        tasks = []
        for format_type in self.CONVERTERS.keys():
            task = asyncio.create_task(self._run_converter_async(format_type))
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        converter_results = {}
        for format_type, result in zip(self.CONVERTERS.keys(), results):
            if isinstance(result, Exception):
                converter_results[format_type] = {
                    'success': False,
                    'format': format_type,
                    'error': str(result)
                }
            else:
                converter_results[format_type] = result

        # Summary
        successful = sum(1 for r in converter_results.values() if r.get('success'))
        failed = len(converter_results) - successful

        return {
            'summary': {
                'total': len(converter_results),
                'successful': successful,
                'failed': failed
            },
            'results': converter_results
        }

    async def _run_converter_async(self, format_type: str) -> Dict:
        """
        Run converter asynchronously
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.run_converter, format_type)

    def validate_outputs(self) -> Dict:
        """
        Validate that all expected outputs were generated
        """
        logger.info("Validating converter outputs...")

        validation_results = {}

        for format_type, info in self.CONVERTERS.items():
            output_dir = self.project_path / info['output_folder']

            if not output_dir.exists():
                validation_results[format_type] = {
                    'valid': False,
                    'error': f"Output directory does not exist: {output_dir}"
                }
                continue

            # Check for expected file types
            files_found = []
            for ext in info['extensions']:
                files_found.extend(list(output_dir.glob(f"*{ext}")))

            if not files_found:
                validation_results[format_type] = {
                    'valid': False,
                    'error': f"No {info['extensions']} files found in {output_dir}"
                }
            else:
                validation_results[format_type] = {
                    'valid': True,
                    'files': [f.name for f in files_found],
                    'count': len(files_found)
                }

        # Overall validation
        all_valid = all(r.get('valid', False) for r in validation_results.values())

        return {
            'valid': all_valid,
            'formats': validation_results
        }

    def clean_output_folders(self):
        """
        Clean all output folders (useful for re-running converters)
        """
        logger.info("Cleaning output folders...")

        for format_type, info in self.CONVERTERS.items():
            output_dir = self.project_path / info['output_folder']
            if output_dir.exists():
                for file in output_dir.glob('*'):
                    file.unlink()
                logger.info(f"Cleaned {format_type} output folder")


def run_converters_for_project(project_folder: str, formats: Optional[List[str]] = None) -> Dict:
    """
    Convenience function to run converters for a project

    Args:
        project_folder: Project folder name
        formats: List of formats to convert to (None = all)

    Returns:
        Conversion results
    """
    runner = ConverterRunner(project_folder)

    if formats:
        results = {}
        for format_type in formats:
            results[format_type] = runner.run_converter(format_type)
        return results
    else:
        return runner.run_all_converters(parallel=True)