#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Error Handling Module - TC #50 FIX 6
==========================================

Provides robust error handling utilities for the KiCad conversion pipeline:
- Retry decorator with exponential backoff
- Error categorization (recoverable vs fatal)
- Graceful degradation support
- Detailed error logging

Design Principles:
- GENERIC: Works for any conversion operation
- RESILIENT: Retries transient failures automatically
- GRACEFUL: Falls back to partial output when full conversion fails
- LOGGED: All errors and retries are clearly logged

Author: CopperPilot AI System (TC #50)
Date: 2025-11-25
"""

import time
import logging
from functools import wraps
from typing import Optional, Callable, Any, TypeVar, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# ERROR CATEGORIES
# ============================================================================

class ErrorCategory(Enum):
    """Categories of errors for handling decisions."""
    RECOVERABLE = "recoverable"   # May succeed on retry (timeout, API limit, file lock)
    FATAL = "fatal"               # Cannot recover (invalid input, missing dependency)
    DEGRADABLE = "degradable"     # Can fallback to simpler output (routing failure)


class RecoverableError(Exception):
    """
    Errors that may succeed on retry.

    Examples:
    - API timeout
    - File lock contention
    - Temporary network failure
    - Resource busy
    """
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error


class FatalError(Exception):
    """
    Errors that cannot be recovered through retry.

    Examples:
    - Invalid input data
    - Missing required dependency
    - Permission denied
    - Corrupted file
    """
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error


class DegradableError(Exception):
    """
    Errors that allow graceful degradation.

    The conversion can continue with reduced functionality.

    Examples:
    - Routing failure (can still produce unrouted PCB)
    - Validation failure (can still produce files)
    - AI fixer failure (can continue without AI fixes)
    """
    def __init__(self, message: str, degradation_level: int = 1,
                 original_error: Optional[Exception] = None):
        super().__init__(message)
        self.degradation_level = degradation_level
        self.original_error = original_error


# ============================================================================
# RETRY DECORATOR
# ============================================================================

T = TypeVar('T')

def with_retry(
    max_attempts: int = 3,
    backoff: float = 1.0,
    max_backoff: float = 30.0,
    recoverable_exceptions: Tuple[type, ...] = (RecoverableError, TimeoutError, ConnectionError),
    on_retry: Optional[Callable[[Exception, int], None]] = None
):
    """
    Decorator for automatic retry with exponential backoff.

    TC #50 FIX 6: Handles transient failures automatically.

    Args:
        max_attempts: Maximum number of attempts (default: 3)
        backoff: Initial backoff delay in seconds (default: 1.0)
        max_backoff: Maximum backoff delay in seconds (default: 30.0)
        recoverable_exceptions: Tuple of exception types to retry on
        on_retry: Optional callback called on each retry with (exception, attempt)

    Returns:
        Decorated function with retry logic

    Usage:
        @with_retry(max_attempts=3, backoff=2.0)
        def call_api():
            # API call that may fail transiently
            pass

    Example:
        @with_retry(max_attempts=5, recoverable_exceptions=(TimeoutError, APIError))
        def fetch_data():
            return api.get_data()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)

                except recoverable_exceptions as e:
                    last_exception = e

                    if attempt == max_attempts - 1:
                        # Last attempt failed, re-raise
                        logger.error(f"❌ {func.__name__} failed after {max_attempts} attempts: {e}")
                        raise

                    # Calculate backoff with exponential increase
                    delay = min(backoff * (2 ** attempt), max_backoff)

                    logger.warning(
                        f"⚠️  {func.__name__} attempt {attempt + 1}/{max_attempts} failed: {e}"
                    )
                    logger.info(f"   ↻ Retrying in {delay:.1f}s...")

                    # Optional retry callback
                    if on_retry:
                        on_retry(e, attempt)

                    time.sleep(delay)

                except Exception as e:
                    # Non-recoverable exception, don't retry
                    logger.error(f"❌ {func.__name__} fatal error: {e}")
                    raise

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


# ============================================================================
# ERROR CATEGORIZATION
# ============================================================================

def categorize_error(error: Exception) -> ErrorCategory:
    """
    Categorize an error for handling decisions.

    TC #50 FIX 6: Determines if error is recoverable, fatal, or allows degradation.

    Args:
        error: The exception to categorize

    Returns:
        ErrorCategory indicating how to handle the error
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    # Recoverable errors (can retry)
    recoverable_patterns = [
        'timeout', 'timed out', 'connection reset', 'connection refused',
        'rate limit', 'too many requests', 'service unavailable',
        'temporary', 'resource busy', 'file lock', 'try again',
        'anthropic', 'openai', 'api',  # AI API errors often recoverable
    ]

    for pattern in recoverable_patterns:
        if pattern in error_str or pattern in error_type:
            return ErrorCategory.RECOVERABLE

    # Degradable errors (can fallback)
    degradable_patterns = [
        'routing', 'freerouting', 'autoroute', 'ses', 'dsn',
        'validation', 'drc', 'erc',
        'ai fixer', 'ai fix', 'claude', 'anthropic',
    ]

    for pattern in degradable_patterns:
        if pattern in error_str or pattern in error_type:
            return ErrorCategory.DEGRADABLE

    # Fatal errors (cannot recover)
    fatal_patterns = [
        'invalid', 'malformed', 'corrupt', 'permission denied',
        'not found', 'does not exist', 'missing', 'required',
        'syntax error', 'parse error', 'import error',
    ]

    for pattern in fatal_patterns:
        if pattern in error_str or pattern in error_type:
            return ErrorCategory.FATAL

    # Default to fatal for unknown errors
    return ErrorCategory.FATAL


# ============================================================================
# GRACEFUL DEGRADATION
# ============================================================================

@dataclass
class DegradationLevel:
    """Defines a level of graceful degradation."""
    level: int
    name: str
    description: str
    features_enabled: list


# Define degradation levels (higher = more degraded)
DEGRADATION_LEVELS = {
    0: DegradationLevel(
        level=0,
        name="FULL",
        description="Full conversion: Schematic + PCB + Routing + Validation",
        features_enabled=["schematic", "pcb", "routing", "validation", "ai_fixer"]
    ),
    1: DegradationLevel(
        level=1,
        name="NO_AI",
        description="No AI: Schematic + PCB + Routing + Validation (no AI fixer)",
        features_enabled=["schematic", "pcb", "routing", "validation"]
    ),
    2: DegradationLevel(
        level=2,
        name="NO_ROUTING",
        description="No routing: Schematic + PCB + Validation (ratsnest only)",
        features_enabled=["schematic", "pcb", "validation"]
    ),
    3: DegradationLevel(
        level=3,
        name="NO_VALIDATION",
        description="No validation: Schematic + PCB (unvalidated)",
        features_enabled=["schematic", "pcb"]
    ),
    4: DegradationLevel(
        level=4,
        name="SCHEMATIC_ONLY",
        description="Schematic only: No PCB generated",
        features_enabled=["schematic"]
    ),
}


class ConversionContext:
    """
    Context manager for graceful degradation during conversion.

    TC #50 FIX 6: Tracks degradation level and allows fallback.

    Usage:
        with ConversionContext() as ctx:
            ctx.attempt_feature("routing", route_board)
            ctx.attempt_feature("validation", validate_pcb)

            # Check final state
            if ctx.degradation_level > 0:
                print(f"Completed with degradation: {ctx.current_level.name}")
    """

    def __init__(self, initial_level: int = 0):
        self.degradation_level = initial_level
        self.failed_features = []
        self.successful_features = []
        self.errors = []

    @property
    def current_level(self) -> DegradationLevel:
        """Get current degradation level definition."""
        return DEGRADATION_LEVELS.get(self.degradation_level, DEGRADATION_LEVELS[4])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Log final status
        if self.degradation_level > 0:
            logger.warning(
                f"⚠️  Conversion completed with degradation level {self.degradation_level}: "
                f"{self.current_level.name}"
            )
            if self.failed_features:
                logger.warning(f"   Failed features: {', '.join(self.failed_features)}")
        return False  # Don't suppress exceptions

    def attempt_feature(
        self,
        feature_name: str,
        func: Callable[..., Any],
        *args,
        fallback_level: int = 1,
        **kwargs
    ) -> Tuple[bool, Any]:
        """
        Attempt a feature with graceful degradation.

        Args:
            feature_name: Name of the feature (for logging)
            func: Function to call
            *args: Arguments for func
            fallback_level: Level to degrade to on failure
            **kwargs: Keyword arguments for func

        Returns:
            Tuple of (success, result_or_none)
        """
        try:
            result = func(*args, **kwargs)
            self.successful_features.append(feature_name)
            logger.info(f"✅ {feature_name} completed successfully")
            return (True, result)

        except Exception as e:
            category = categorize_error(e)
            self.errors.append((feature_name, e))

            if category == ErrorCategory.FATAL:
                logger.error(f"❌ {feature_name} fatal error: {e}")
                raise  # Re-raise fatal errors

            # Degradable or recoverable error
            self.failed_features.append(feature_name)
            self.degradation_level = max(self.degradation_level, fallback_level)

            logger.warning(
                f"⚠️  {feature_name} failed (degrading to level {self.degradation_level}): {e}"
            )

            return (False, None)

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if a feature is enabled at current degradation level."""
        return feature_name in self.current_level.features_enabled


# ============================================================================
# LOGGING UTILITIES
# ============================================================================

def log_error_context(error: Exception, context: dict = None):
    """
    Log an error with additional context for debugging.

    TC #50 FIX 6: Provides detailed error logging for diagnosis.

    Args:
        error: The exception to log
        context: Additional context dictionary
    """
    category = categorize_error(error)

    logger.error(f"{'='*60}")
    logger.error(f"ERROR: {type(error).__name__}")
    logger.error(f"Message: {str(error)}")
    logger.error(f"Category: {category.value}")

    if context:
        logger.error("Context:")
        for key, value in context.items():
            logger.error(f"  {key}: {value}")

    if hasattr(error, 'original_error') and error.original_error:
        logger.error(f"Original error: {error.original_error}")

    logger.error(f"{'='*60}")


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def wrap_as_recoverable(func: Callable, *recoverable_exceptions):
    """
    Wrap a function to convert specified exceptions to RecoverableError.

    Args:
        func: Function to wrap
        *recoverable_exceptions: Exception types to convert

    Returns:
        Wrapped function
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except recoverable_exceptions as e:
            raise RecoverableError(str(e), original_error=e)
    return wrapper


# Export all public symbols
__all__ = [
    'ErrorCategory',
    'RecoverableError',
    'FatalError',
    'DegradableError',
    'with_retry',
    'categorize_error',
    'DegradationLevel',
    'DEGRADATION_LEVELS',
    'ConversionContext',
    'log_error_context',
    'wrap_as_recoverable',
]
