# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Enhanced Logging System - PRODUCTION READY
Implements comprehensive logging for debugging and AI training
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List
import traceback
import pprint


class EnhancedLogger:
    """
    Enhanced logger that creates structured logs per run.
    CRITICAL: This logger MUST capture ALL inputs, outputs, and processing steps.

    Structure:
    logs/
    ├── main.log (daily archived)
    └── runs/
        └── YYYYMMDD-HHMMSS-UNIQUE/
            ├── main.log (run-specific verbose log)
            ├── steps/
            │   ├── step1_info_gathering.log
            │   ├── step2_high_level.log
            │   ├── step3_low_level.log
            │   ├── step4_bom.log
            │   ├── step5_conversion.log
            │   └── step6_packaging.log
            └── ai_training/
                ├── step1_TIMESTAMP_prompt.txt
                ├── step1_TIMESTAMP_response.txt
                └── step1_TIMESTAMP_metadata.json
    """

    def __init__(self, project_folder: str, logs_dir: Path):
        """
        Initialize enhanced logger for a specific project run.

        Args:
            project_folder: The unique project folder name (e.g., "20250925-081234-abc123")
            logs_dir: Path to the logs directory for this run
        """
        self.project_folder = project_folder
        self.logs_dir = logs_dir
        self.steps_dir = logs_dir / 'steps'
        self.ai_dir = logs_dir / 'ai_training'

        # Ensure directories exist
        self.steps_dir.mkdir(parents=True, exist_ok=True)
        self.ai_dir.mkdir(parents=True, exist_ok=True)

        # Pretty printer for structured data
        self.pp = pprint.PrettyPrinter(indent=2, width=120)

        # Set up main logger for this run
        self.main_logger = self._setup_logger(
            f"run.{project_folder}",
            logs_dir / 'main.log',
            level=logging.DEBUG  # Capture everything
        )

        # Set up step-specific loggers with DEBUG level
        self.step_loggers = {}
        self.step_names = {
            'step1_info_gathering': 'Step 1: Information Gathering',
            'step2_high_level': 'Step 2: High-Level Design',
            'step3_low_level': 'Step 3: Low-Level Circuit Design',
            'step4_conversion': 'Step 4: Format Conversion',
            'step5_bom': 'Step 5: BOM & Parts Selection',
            'step6_qa': 'Step 6: Quality Assurance',
            'step7_packaging': 'Step 7: Final Packaging'
        }

        for step_name in self.step_names.keys():
            self.step_loggers[step_name] = self._setup_logger(
                f"run.{project_folder}.{step_name}",
                self.steps_dir / f"{step_name}.log",
                level=logging.DEBUG
            )

        # Also update the global main.log
        self.global_logger = logging.getLogger('main')
        if not self.global_logger.handlers:
            handler = logging.FileHandler('logs/main.log')
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
            self.global_logger.addHandler(handler)
            self.global_logger.setLevel(logging.INFO)

        # Phase F (Forensic Fix 20260208): Bridge step loggers so that
        # messages from workflow.step_3_low_level (etc.) also reach per-run files.
        self.bridge_step_loggers()

        # Log initialization
        self.main_logger.info("=" * 80)
        self.main_logger.info(f"ENHANCED LOGGER INITIALIZED")
        self.main_logger.info(f"Project: {project_folder}")
        self.main_logger.info(f"Logs Directory: {logs_dir}")
        self.main_logger.info("=" * 80)

    def _setup_logger(self, name: str, log_file: Path, level=logging.DEBUG) -> logging.Logger:
        """Set up a logger with file handler"""
        logger = logging.getLogger(name)
        logger.setLevel(level)

        # Remove existing handlers to avoid duplicates
        logger.handlers.clear()

        # Create file handler with UTF-8 encoding
        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setLevel(level)

        # Create detailed formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)

        # Add handler
        logger.addHandler(handler)

        # Prevent propagation to avoid duplicate logs
        logger.propagate = False

        return logger

    # Map from Python module names used in workflow code to step log names.
    # The keys are substrings that appear in logger names created by
    # setup_logger(__name__) in the workflow modules.
    _STEP_LOGGER_MAPPING = {
        'step_1': 'step1_info_gathering',
        'step_2': 'step2_high_level',
        'step_3': 'step3_low_level',
        'step_4': 'step4_conversion',
        'step_5': 'step5_bom',
        'step_6': 'step6_qa',
        'step_7': 'step7_packaging',
        'circuit_supervisor': 'step3_low_level',
        'circuit_fixer': 'step3_low_level',
        'design_supervisor': 'step3_low_level',
        'integration_agent': 'step3_low_level',
        'module_agent': 'step3_low_level',
        'component_agent': 'step3_low_level',
        'connection_agent': 'step3_low_level',
        'validation_agent': 'step3_low_level',
        'rating_validator': 'step3_low_level',
        'quality_assurance': 'step6_qa',
        'bom': 'step5_bom',
        'generate_assembly': 'step7_packaging',
    }

    def bridge_step_loggers(self) -> None:
        """
        Phase F (Forensic Fix 20260208): Bridge existing workflow loggers to per-run files.

        The workflow code calls ``setup_logger(__name__)`` which creates loggers
        like ``workflow.step_3_low_level``.  The EnhancedLogger creates separate
        loggers like ``run.<project>.step3_low_level``.  Messages from the first
        set never reach the second set's file handlers — hence 0-byte step logs.

        This method finds all existing loggers whose names contain step keywords
        and attaches the matching per-run file handler to them.
        """
        manager = logging.Logger.manager
        bridged = 0

        # Also check loggers that haven't been created yet but will be
        for logger_name in list(getattr(manager, 'loggerDict', {}).keys()):
            for keyword, step_name in self._STEP_LOGGER_MAPPING.items():
                if keyword in logger_name.lower():
                    step_logger_instance = self.step_loggers.get(step_name)
                    if step_logger_instance and step_logger_instance.handlers:
                        target_logger = logging.getLogger(logger_name)
                        # Add the per-run file handler if not already present
                        handler = step_logger_instance.handlers[0]
                        if handler not in target_logger.handlers:
                            target_logger.addHandler(handler)
                            bridged += 1
                    break

        # Also add main run handler to the root workflow loggers
        if self.main_logger.handlers:
            main_handler = self.main_logger.handlers[0]
            for logger_name in list(getattr(manager, 'loggerDict', {}).keys()):
                if 'workflow' in logger_name.lower() or 'circuit' in logger_name.lower():
                    target_logger = logging.getLogger(logger_name)
                    if main_handler not in target_logger.handlers:
                        target_logger.addHandler(main_handler)

        if bridged > 0:
            self.main_logger.info(f"Phase F: Bridged {bridged} workflow loggers to per-run step files")

    def log(self, message: str, level: str = 'info'):
        """Log to main run logger and global logger"""
        log_func = getattr(self.main_logger, level.lower(), self.main_logger.info)
        log_func(message)

        # Also log to global
        global_func = getattr(self.global_logger, level.lower(), self.global_logger.info)
        global_func(f"[{self.project_folder}] {message}")

    def log_step_input(self, step: str, input_data: Any, description: str = ""):
        """
        Log the complete input for a step.
        CRITICAL: Must capture FULL input data for debugging.
        """
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)

        logger = self.step_loggers.get(step, self.main_logger)

        logger.info("=" * 80)
        logger.info(f"STEP INPUT: {self.step_names.get(step, step)}")
        if description:
            logger.info(f"Description: {description}")
        logger.info("=" * 80)

        # Log the complete input data
        if isinstance(input_data, (dict, list)):
            logger.info("Input Data (structured):")
            for line in self.pp.pformat(input_data).split('\n'):
                logger.info(f"  {line}")
        else:
            logger.info(f"Input Data: {input_data}")

        logger.info("-" * 80)

        # Also log summary to main
        self.log(f"[{step}] INPUT: {description or 'Processing input'}")

    def log_step_output(self, step: str, output_data: Any, description: str = ""):
        """
        Log the complete output for a step.
        CRITICAL: Must capture FULL output data for debugging.
        """
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)

        logger = self.step_loggers.get(step, self.main_logger)

        logger.info("=" * 80)
        logger.info(f"STEP OUTPUT: {self.step_names.get(step, step)}")
        if description:
            logger.info(f"Description: {description}")
        logger.info("=" * 80)

        # Log the complete output data
        if isinstance(output_data, (dict, list)):
            logger.info("Output Data (structured):")
            for line in self.pp.pformat(output_data).split('\n'):
                logger.info(f"  {line}")
        else:
            logger.info(f"Output Data: {output_data}")

        logger.info("-" * 80)

        # Also log summary to main
        self.log(f"[{step}] OUTPUT: {description or 'Processing complete'}")

    def log_step_processing(self, step: str, message: str, level: str = 'info'):
        """Log processing steps within a workflow step"""
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)

        logger = self.step_loggers.get(step, self.main_logger)
        log_func = getattr(logger, level.lower(), logger.info)
        log_func(f"[PROCESSING] {message}")

        # Also log to main
        self.log(f"[{step}] {message}", level)

    def log_step(self, step: str, message: str, level: str = 'info'):
        """Log to specific step logger"""
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)

        if step in self.step_loggers:
            log_func = getattr(self.step_loggers[step], level.lower(),
                             self.step_loggers[step].info)
            log_func(message)

        # Also log to main run logger
        self.log(f"[{step}] {message}", level)

    def log_error(self, step: str, error: Exception, include_traceback: bool = True):
        """Log error with full traceback"""
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)

        error_msg = f"ERROR in {self.step_names.get(step, step)}: {str(error)}"

        if step in self.step_loggers:
            self.step_loggers[step].error("=" * 80)
            self.step_loggers[step].error(error_msg)
            if include_traceback:
                self.step_loggers[step].error("Traceback:")
                for line in traceback.format_exc().split('\n'):
                    self.step_loggers[step].error(f"  {line}")
            self.step_loggers[step].error("=" * 80)

        # Also log to main
        self.main_logger.error(error_msg)
        if include_traceback:
            self.main_logger.error(f"Full traceback:\n{traceback.format_exc()}")

    def log_warning(self, step: str, message: str, context: str = ""):
        """Log warning with context"""
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)

        warning_msg = f"WARNING: {message}"
        if context:
            warning_msg = f"WARNING [{context}]: {message}"

        if step in self.step_loggers:
            self.step_loggers[step].warning(warning_msg)

        # Also log to main
        self.log(f"[{step}] {warning_msg}", 'warning')

    def save_ai_interaction(self, step: str, prompt: str, response: str,
                          metadata: Optional[Dict[str, Any]] = None,
                          interaction_type: str = ""):
        """
        Save AI interaction for training data collection.
        CRITICAL: Must save ALL AI interactions for debugging and training.

        Args:
            step: Step name (e.g., 'step1', 'step2')
            prompt: The complete prompt sent to AI
            response: The complete AI response
            metadata: Optional metadata (model, temperature, cost, tokens, duration)
            interaction_type: Type of interaction (e.g., 'main', 'consolidation', 'fix')
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]  # Include milliseconds

        # Normalize step name
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)

        # Add interaction type to filename if provided
        suffix = f"_{interaction_type}" if interaction_type else ""

        # Save prompt
        prompt_file = self.ai_dir / f"{step}_{timestamp}{suffix}_prompt.txt"
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)

        # Save response
        response_file = self.ai_dir / f"{step}_{timestamp}{suffix}_response.txt"
        with open(response_file, 'w', encoding='utf-8') as f:
            f.write(response)

        # Enhance metadata
        if metadata is None:
            metadata = {}

        metadata.update({
            'timestamp': timestamp,
            'step': step,
            'interaction_type': interaction_type,
            'prompt_length': len(prompt),
            'response_length': len(response),
            'prompt_file': str(prompt_file.name),
            'response_file': str(response_file.name)
        })

        # Save metadata
        metadata_file = self.ai_dir / f"{step}_{timestamp}{suffix}_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, default=str)

        # Log to step logger
        if step in self.step_loggers:
            self.step_loggers[step].info(f"AI Interaction saved: {timestamp}{suffix}")
            self.step_loggers[step].info(f"  Model: {metadata.get('model', 'unknown')}")
            self.step_loggers[step].info(f"  Prompt: {len(prompt)} chars")
            self.step_loggers[step].info(f"  Response: {len(response)} chars")
            if 'cost' in metadata:
                self.step_loggers[step].info(f"  Cost: ${metadata['cost']:.4f}")
            if 'duration' in metadata:
                self.step_loggers[step].info(f"  Duration: {metadata['duration']:.2f}s")

        self.log_step(step, f"AI interaction saved: {timestamp}{suffix}", 'debug')

    def log_subprocess(self, step: str, command: str, output: str, error: str = "",
                      return_code: int = 0):
        """Log subprocess execution (converters, graphviz, etc)"""
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)

        logger = self.step_loggers.get(step, self.main_logger)

        logger.info(f"[SUBPROCESS] Command: {command}")
        logger.info(f"[SUBPROCESS] Return Code: {return_code}")

        if output:
            logger.info(f"[SUBPROCESS] Output:")
            for line in output.split('\n'):
                logger.info(f"  {line}")

        if error:
            logger.warning(f"[SUBPROCESS] Error:")
            for line in error.split('\n'):
                logger.warning(f"  {line}")

    def log_step_start(self, step: str, description: str = ""):
        """
        Phase G (Forensic Fix 20260211): Log step start marker.
        Standardizes step entry for easier forensic trace analysis.
        """
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)
            
        logger = self.step_loggers.get(step, self.main_logger)
        
        logger.info("\n" + "#" * 100)
        logger.info(f"### BEGIN STEP: {self.step_names.get(step, step)}")
        if description:
            logger.info(f"### Description: {description}")
        logger.info(f"### Timestamp: {datetime.now().isoformat()}")
        logger.info("#" * 100 + "\n")
        
        self.log(f"[{step}] >>> BEGIN: {description or 'Processing'}")

    def log_step_end(self, step: str, success: bool, message: str = ""):
        """
        Phase G (Forensic Fix 20260211): Log step end marker and gate verdict.
        Standardizes step exit for easier forensic trace analysis.
        """
        if step not in self.step_loggers:
            step = self._normalize_step_name(step)
            
        logger = self.step_loggers.get(step, self.main_logger)
        
        verdict = "PASS" if success else "FAIL"
        
        logger.info("\n" + "#" * 100)
        logger.info(f"### END STEP: {self.step_names.get(step, step)}")
        logger.info(f"### VERDICT: {verdict}")
        if message:
            logger.info(f"### Message: {message}")
        logger.info(f"### Timestamp: {datetime.now().isoformat()}")
        logger.info("#" * 100 + "\n")
        
        self.log(f"[{step}] <<< END [{verdict}]: {message or 'Done'}")

    def log_workflow_start(self, requirements: Dict):
        """Log workflow start with complete requirements"""
        self.main_logger.info("=" * 100)
        self.main_logger.info("WORKFLOW STARTED")
        self.main_logger.info(f"Timestamp: {datetime.now().isoformat()}")
        self.main_logger.info(f"Project Folder: {self.project_folder}")
        self.main_logger.info("-" * 100)
        self.main_logger.info("Requirements:")
        for line in self.pp.pformat(requirements).split('\n'):
            self.main_logger.info(f"  {line}")
        self.main_logger.info("=" * 100)

    def log_workflow_complete(self, success: bool, duration: float, output_dir: str,
                            summary: Optional[Dict] = None):
        """Log workflow completion with summary"""
        self.main_logger.info("=" * 100)
        self.main_logger.info(f"WORKFLOW {'COMPLETED SUCCESSFULLY' if success else 'FAILED'}")
        self.main_logger.info(f"Duration: {duration:.2f} seconds")
        self.main_logger.info(f"Output Directory: {output_dir}")

        if summary:
            self.main_logger.info("Summary:")
            for key, value in summary.items():
                self.main_logger.info(f"  {key}: {value}")

        self.main_logger.info("=" * 100)

    def _normalize_step_name(self, step: str) -> str:
        """Normalize step name to match our convention"""
        # Handle various step name formats
        # Updated for 7-step workflow: 1-Info, 2-HighLevel, 3-Circuits, 4-Conversion, 5-BOM, 6-QA, 7-Package
        step_mapping = {
            'step1': 'step1_info_gathering',
            'step_1': 'step1_info_gathering',
            'step_1_gather_info': 'step1_info_gathering',
            'step2': 'step2_high_level',
            'step_2': 'step2_high_level',
            'step_2_high_level': 'step2_high_level',
            'step2_high': 'step2_high_level',
            'step3': 'step3_low_level',
            'step_3': 'step3_low_level',
            'step_3_low_level': 'step3_low_level',
            'step4': 'step4_conversion',
            'step_4': 'step4_conversion',
            'step_4_conversion': 'step4_conversion',
            'step_4_convert': 'step4_conversion',
            'step5': 'step5_bom',
            'step_5': 'step5_bom',
            'step_5_bom': 'step5_bom',
            'step_4_bom': 'step5_bom',  # Legacy mapping
            'step6': 'step6_qa',
            'step_6': 'step6_qa',
            'step_6_qa': 'step6_qa',
            'step7': 'step7_packaging',
            'step_7': 'step7_packaging',
            'step_7_packaging': 'step7_packaging',
            'step_6_packaging': 'step7_packaging'  # Legacy mapping
        }

        return step_mapping.get(step.lower(), step)

    def archive_daily_log(self):
        """Archive main.log if it's a new day"""
        main_log = Path('logs/main.log')
        if main_log.exists():
            # Check if log is from previous day
            mod_time = datetime.fromtimestamp(main_log.stat().st_mtime)
            if mod_time.date() < datetime.now().date():
                # Archive the log
                archive_dir = Path('logs/archive')
                archive_dir.mkdir(exist_ok=True)

                archive_name = f"main_{mod_time.strftime('%Y%m%d')}.log"
                archive_path = archive_dir / archive_name

                main_log.rename(archive_path)
                self.global_logger.info(f"Archived previous log to {archive_path}")

    def flush_all(self):
        """Flush all log handlers to ensure everything is written"""
        for logger in [self.main_logger, self.global_logger] + list(self.step_loggers.values()):
            for handler in logger.handlers:
                handler.flush()