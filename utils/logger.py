# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Comprehensive logging system for debugging
This is what N8N lacks - proper logging!
Enhanced with multi-file logging, rotation, and web server support
"""
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List
import traceback
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

# Optional third-party logging enhancements. Fall back gracefully if missing.
try:  # structlog is optional; this module uses stdlib logging as primary sink
    import structlog  # noqa: F401
except Exception:
    structlog = None  # Not required; kept for compatibility if present

try:
    from rich.logging import RichHandler  # Rich console rendering
    from rich.console import Console
    _HAS_RICH = True
except Exception:
    RichHandler = None  # type: ignore
    Console = None      # type: ignore
    _HAS_RICH = False

from server.config import config

# Create console for rich output if available
console = Console() if _HAS_RICH else None

# Define comprehensive log directory structure
LOG_BASE_DIR = Path("logs")
LOG_STRUCTURE = {
    "main": LOG_BASE_DIR / "main.log",
    "chat": {
        "conversations": LOG_BASE_DIR / "chat" / "conversations.log",
        "ai_interactions": LOG_BASE_DIR / "chat" / "ai_interactions.log"
    },
    "steps": {
        "step1_info": LOG_BASE_DIR / "steps" / "step1_info_gathering.log",
        "step2_high": LOG_BASE_DIR / "steps" / "step2_high_level.log",
        "step3_low": LOG_BASE_DIR / "steps" / "step3_low_level.log",
        "step4_bom": LOG_BASE_DIR / "steps" / "step4_bom.log",
        "step5_convert": LOG_BASE_DIR / "steps" / "step5_conversion.log",
        "step6_package": LOG_BASE_DIR / "steps" / "step6_packaging.log"
    },
    "archive": LOG_BASE_DIR / "archive"
}

# Create all necessary directories
for key, value in LOG_STRUCTURE.items():
    if isinstance(value, dict):
        for subkey, path in value.items():
            path.parent.mkdir(parents=True, exist_ok=True)
    elif isinstance(value, Path):
        value.parent.mkdir(parents=True, exist_ok=True)

def setup_logger(name: str) -> logging.Logger:
    """
    Set up a structured logger with rich formatting and file output

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger instance
    """
    # Get Python's standard logger
    logger = logging.getLogger(name)
    logger.setLevel(config.LOG_LEVEL)

    # Clear any existing handlers
    logger.handlers = []

    # Console handler with rich formatting
    if _HAS_RICH and console is not None:
        console_handler = RichHandler(
            console=console,
            rich_tracebacks=True,
            tracebacks_show_locals=True
        )
        console_handler.setLevel(config.LOG_LEVEL)
        logger.addHandler(console_handler)
    else:
        # Fallback to a simple stream handler if rich is unavailable
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(config.LOG_LEVEL)
        stream_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        stream_handler.setFormatter(stream_formatter)
        logger.addHandler(stream_handler)

    # File handler for main log
    main_log_path = LOG_STRUCTURE["main"]
    main_log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        main_log_path,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(config.LOG_LEVEL)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Add step-specific file handler if it's a step logger
    for step_name, step_path in LOG_STRUCTURE["steps"].items():
        if step_name in name.lower() or step_name.replace("_", "") in name.lower().replace("_", ""):
            step_path.parent.mkdir(parents=True, exist_ok=True)
            step_handler = RotatingFileHandler(
                step_path,
                maxBytes=5*1024*1024,  # 5MB
                backupCount=3
            )
            step_handler.setLevel(logging.DEBUG)  # Always capture DEBUG for step logs
            step_handler.setFormatter(file_formatter)
            logger.addHandler(step_handler)
            # Also add to chat logs if it's AI interaction
            if "ai" in name.lower() or "chat" in name.lower():
                chat_path = LOG_STRUCTURE["chat"]["ai_interactions"]
                chat_path.parent.mkdir(parents=True, exist_ok=True)
                chat_handler = RotatingFileHandler(
                    chat_path,
                    maxBytes=5*1024*1024,
                    backupCount=3
                )
                chat_handler.setLevel(logging.DEBUG)
                chat_handler.setFormatter(file_formatter)
                logger.addHandler(chat_handler)
            break

    return logger

class WorkflowLogger:
    """
    Specialized logger for workflow steps
    Saves everything for debugging!
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.log_dir = config.LOGS_DIR / project_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = setup_logger(f"workflow.{project_id}")

    def log_step(
        self,
        step_name: str,
        event_type: str,
        data: Any,
        context: Optional[Dict] = None
    ):
        """
        Log a workflow step with full data

        Args:
            step_name: Name of the workflow step
            event_type: Type of event (input, output, error, etc.)
            data: Data to log
            context: Additional context
        """

        timestamp = datetime.now().isoformat()

        # Create log entry
        log_entry = {
            "timestamp": timestamp,
            "project_id": self.project_id,
            "step": step_name,
            "event_type": event_type,
            "data": data,
            "context": context or {}
        }

        # Save to file for debugging
        log_file = self.log_dir / f"{step_name}_{event_type}_{timestamp.replace(':', '-')}.json"

        try:
            with open(log_file, 'w') as f:
                json.dump(log_entry, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Failed to write log file: {e}")

        # Also log to console/structured log
        self.logger.info(
            f"Step: {step_name} | Event: {event_type} | Has Data: {bool(data)}"
        )

    def log_input(self, step_name: str, input_data: Any):
        """Log step input for replay capability"""
        self.log_step(step_name, "input", input_data)

    def log_output(self, step_name: str, output_data: Any):
        """Log step output"""
        self.log_step(step_name, "output", output_data)

    def log_error(self, step_name: str, error: Exception, context: Optional[Dict] = None):
        """Log step error with full traceback"""
        import traceback

        error_data = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc()
        }

        self.log_step(step_name, "error", error_data, context)
        self.logger.error(
            f"Error in {step_name}: {error}"
        )

    def log_validation(self, step_name: str, validation_result: Dict):
        """Log validation results"""
        self.log_step(step_name, "validation", validation_result)

        if not validation_result.get("valid", False):
            self.logger.warning(
                f"Validation failed for {step_name}",
                issues=validation_result.get("issues", [])
            )

    def log_cost(self, step_name: str, cost: float, tokens: Dict):
        """Log API costs for tracking"""
        cost_data = {
            "cost": cost,
            "tokens": tokens,
            "timestamp": datetime.now().isoformat()
        }

        self.log_step(step_name, "cost", cost_data)

        if cost > config.COST_WARNING_THRESHOLD:
            self.logger.warning(
                f"High cost for {step_name}: ${cost:.2f}",
                tokens=tokens
            )

    def get_step_logs(self, step_name: Optional[str] = None) -> list:
        """
        Retrieve logs for debugging

        Args:
            step_name: Optional step name to filter by

        Returns:
            List of log entries
        """
        logs = []

        pattern = f"{step_name}_*.json" if step_name else "*.json"

        for log_file in sorted(self.log_dir.glob(pattern)):
            try:
                with open(log_file) as f:
                    logs.append(json.load(f))
            except Exception as e:
                self.logger.error(f"Failed to read log file {log_file}: {e}")

        return logs

    def export_debug_package(self) -> Path:
        """
        Export all logs as a debug package
        Useful for sharing debugging information
        """
        import zipfile

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        package_path = config.LOGS_DIR / f"debug_package_{self.project_id}_{timestamp}.zip"

        with zipfile.ZipFile(package_path, 'w') as zf:
            for log_file in self.log_dir.glob("*.json"):
                zf.write(log_file, log_file.name)

        self.logger.info(f"Debug package exported: {package_path}")
        return package_path


class ComprehensiveLogger:
    """
    Enhanced logger with multi-file support and rotation
    Now supports unique folders per run
    """
    _instance = None
    _loggers = {}
    _run_id = None
    _log_base_dir = None

    def __new__(cls, run_id=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._run_id = run_id
            cls._instance._initialize_comprehensive_loggers()
        return cls._instance

    def _initialize_comprehensive_loggers(self):
        """Initialize all specialized loggers with unique run folders"""

        # Setup base directory for this run
        if self._run_id:
            self._log_base_dir = Path("logs/runs") / self._run_id
            self._log_base_dir.mkdir(parents=True, exist_ok=True)

            # Save current run ID
            current_file = Path("logs/current_run.txt")
            current_file.parent.mkdir(exist_ok=True)
            current_file.write_text(self._run_id)

            # Create subdirectories
            (self._log_base_dir / "steps").mkdir(exist_ok=True)
            (self._log_base_dir / "ai_training").mkdir(exist_ok=True)

            # Update LOG_STRUCTURE paths for this run
            main_log_path = self._log_base_dir / "main.log"
        else:
            # Fallback to default structure
            main_log_path = LOG_STRUCTURE["main"]

        # Main logger - captures everything
        self._setup_file_logger(
            "main", main_log_path,
            level=logging.DEBUG, max_bytes=10*1024*1024, backup_count=5
        )

        # Chat conversation logger
        self._setup_file_logger(
            "chat.conversations", LOG_STRUCTURE["chat"]["conversations"],
            level=logging.INFO, max_bytes=5*1024*1024, backup_count=3
        )

        # AI interaction logger (JSON format)
        self._setup_file_logger(
            "chat.ai", LOG_STRUCTURE["chat"]["ai_interactions"],
            level=logging.DEBUG, max_bytes=10*1024*1024, backup_count=5,
            use_json=True
        )

        # Step-specific loggers
        for step_name, default_path in LOG_STRUCTURE["steps"].items():
            if self._run_id:
                step_path = self._log_base_dir / "steps" / default_path.name
            else:
                step_path = default_path

            self._setup_file_logger(
                f"step.{step_name}", step_path,
                level=logging.DEBUG, max_bytes=5*1024*1024, backup_count=3
            )

        # Archive old logs on startup
        self._archive_old_logs()

    def _setup_file_logger(
        self, name: str, filepath: Path,
        level: int = logging.INFO,
        max_bytes: int = 10*1024*1024,
        backup_count: int = 5,
        use_json: bool = False
    ):
        """Setup individual file logger"""
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.handlers = []  # Clear existing handlers

        # File handler with rotation
        file_handler = RotatingFileHandler(
            filepath, maxBytes=max_bytes, backupCount=backup_count
        )

        if use_json:
            # JSON formatter for structured logging
            formatter = logging.Formatter('%(message)s')
        else:
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
            )

        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        self._loggers[name] = logger

    def _archive_old_logs(self):
        """Archive logs older than 7 days"""
        cutoff_date = datetime.now() - timedelta(days=7)
        archive_dir = LOG_STRUCTURE["archive"]
        archive_dir.mkdir(parents=True, exist_ok=True)

        for log_file in LOG_BASE_DIR.glob("**/*.log*"):
            if log_file.is_file() and "archive" not in str(log_file):
                file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if file_mtime < cutoff_date:
                    archive_subdir = archive_dir / file_mtime.strftime("%Y-%m-%d")
                    archive_subdir.mkdir(parents=True, exist_ok=True)
                    archive_path = archive_subdir / log_file.name
                    try:
                        log_file.rename(archive_path)
                    except Exception:
                        pass  # Skip if file is in use

    def log_ai_interaction(
        self, model: str, prompt: str, response: str,
        tokens_used: int = 0, duration: float = 0,
        project_id: str = None, step: str = None, cost: float = None
    ):
        """Log AI model interactions and save for training"""
        logger = self._loggers.get("main", logging.getLogger("main"))

        # Log to main log
        logger.info(f"AI Call: {step} | Model: {model} | Cost: ${cost:.4f}" if cost else f"AI Call: {step} | Model: {model}")

        # Save for AI training if run_id exists
        if self._run_id and self._log_base_dir:
            self.save_ai_training_data(step or "unknown", prompt, response, model, cost)

    def log_step(self, step_name: str, message: str, level: str = "INFO", **kwargs):
        """Log step-specific messages"""
        logger_name = f"step.{step_name}"
        logger = self._loggers.get(logger_name, logging.getLogger(logger_name))
        log_method = getattr(logger, level.lower(), logger.info)
        log_method(message, extra=kwargs)

    def save_ai_training_data(self, step_name: str, prompt: str, response: str, model: str = None, cost: float = None):
        """Save AI prompts and responses for training"""
        if not self._log_base_dir:
            return

        ai_training_dir = self._log_base_dir / "ai_training"
        ai_training_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save prompt
        prompt_file = ai_training_dir / f"{step_name}_{timestamp}_prompt.txt"
        prompt_file.write_text(prompt)

        # Save response
        response_file = ai_training_dir / f"{step_name}_{timestamp}_response.txt"
        response_file.write_text(response)

        # Save metadata
        metadata = {
            "step": step_name,
            "timestamp": timestamp,
            "model": model,
            "cost": cost,
            "prompt_file": prompt_file.name,
            "response_file": response_file.name,
            "prompt_length": len(prompt),
            "response_length": len(response)
        }

        metadata_file = ai_training_dir / f"{step_name}_{timestamp}_metadata.json"
        import json
        metadata_file.write_text(json.dumps(metadata, indent=2))

        logger = self._loggers.get("main", logging.getLogger("main"))
        logger.info(f"AI training data saved: {prompt_file.name} -> {response_file.name}")

    def log_conversation(self, user_input: str, bot_response: str, project_id: str = None):
        """Log chat conversations"""
        logger = self._loggers.get("main", logging.getLogger("main"))
        logger.info(
            f"[{project_id or 'unknown'}] User: {user_input[:200]}... | Bot: {bot_response[:200]}..."
        )

    def log(self, message: str, level: str = "INFO"):
        """Generic log method"""
        logger = self._loggers.get("main", logging.getLogger("main"))
        log_method = getattr(logger, level.lower(), logger.info)
        log_method(message)

    def info(self, message: str):
        """Log info message"""
        self.log(message, "INFO")

    def error(self, message: str, exc_info=False):
        """Log error message with optional exception info"""
        self.log(message, "ERROR")
        if exc_info:
            import traceback
            self.log(f"Traceback:\n{traceback.format_exc()}", "ERROR")

    def warning(self, message: str):
        """Log warning message"""
        self.log(message, "WARNING")

    def debug(self, message: str):
        """Log debug message"""
        self.log(message, "DEBUG")

    def get_recent_logs(self, logger_name: str = "main", lines: int = 100) -> List[str]:
        """Get recent log entries for web display"""
        log_paths = {
            "main": LOG_STRUCTURE["main"],
            "chat.conversations": LOG_STRUCTURE["chat"]["conversations"],
            "chat.ai": LOG_STRUCTURE["chat"]["ai_interactions"],
        }

        # Add step loggers
        for step_name, step_path in LOG_STRUCTURE["steps"].items():
            log_paths[f"step.{step_name}"] = step_path

        log_file = log_paths.get(logger_name)
        if log_file and log_file.exists():
            with open(log_file, 'r') as f:
                all_lines = f.readlines()
                return all_lines[-lines:]
        return []


# Create singleton instance of comprehensive logger
comprehensive_logger = ComprehensiveLogger()


class DebugRecorder:
    """
    Records everything for replay capability
    The key to fixing issues without re-running expensive operations
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.recording_dir = config.LOGS_DIR / project_id / "recordings"
        self.recording_dir.mkdir(parents=True, exist_ok=True)

    def record(self, operation: str, input_data: Any, output_data: Any, metadata: Dict = None):
        """
        Record an operation for replay

        This allows us to test fix logic without calling AI again!
        """
        recording = {
            "operation": operation,
            "input": input_data,
            "output": output_data,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat()
        }

        filename = f"{operation}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.recording_dir / filename

        with open(filepath, 'w') as f:
            json.dump(recording, f, indent=2, default=str)

        return filepath

    def replay(self, operation: str, timestamp: Optional[str] = None) -> Dict:
        """
        Replay a recorded operation

        This is the magic - replay without API costs!
        """
        if timestamp:
            filename = f"{operation}_{timestamp}.json"
            filepath = self.recording_dir / filename
        else:
            # Get the latest recording for this operation
            files = list(self.recording_dir.glob(f"{operation}_*.json"))
            if not files:
                raise FileNotFoundError(f"No recordings found for operation: {operation}")
            filepath = max(files, key=lambda f: f.stat().st_mtime)

        with open(filepath) as f:
            return json.load(f)
