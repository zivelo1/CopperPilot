#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Timeout Manager - Universal timeout and logging utilities for KiCad converter

PURPOSE:
    Provides context managers and decorators for:
    1. Hard timeouts at function/block level (prevents infinite loops)
    2. Performance profiling (tracks time spent in each function)
    3. Aggressive logging (entry/exit/errors automatically logged)

GENERIC DESIGN:
    - Works with ANY function (not specific to KiCad)
    - No hardcoded timeouts (passed as parameters)
    - Comprehensive error messages for debugging

USAGE:
    from utils.timeout_manager import with_timeout, timed_operation, log_function

    # Method 1: Context manager
    with with_timeout(30, "Component placement"):
        place_component(...)

    # Method 2: Decorator
    @with_timeout_decorator(60, "Circuit conversion")
    def convert_circuit(...):
        ...

    # Method 3: Automatic logging
    @log_function
    def my_function(arg1, arg2):
        ...  # Automatically logs ENTER/EXIT/time/errors

CREATED: 2025-11-19 (Phase 0 - Emergency Triage)
AUTHOR: Claude (CopperPilot systematic fix implementation)
"""

import signal
import logging
import time
import functools
from contextlib import contextmanager
from typing import Callable, Any, Optional
from pathlib import Path


class TimeoutError(Exception):
    """
    Custom timeout exception

    Raised when an operation exceeds its allotted time.
    Includes context about what timed out and why.
    """
    pass


@contextmanager
def with_timeout(seconds: int, operation_name: str = "Operation"):
    """
    Context manager for hard timeouts (POSIX systems only)

    Usage:
        with with_timeout(30, "Component placement"):
            expensive_operation()

    Args:
        seconds: Maximum time allowed (in seconds)
        operation_name: Human-readable name for error messages

    Raises:
        TimeoutError: If operation exceeds time limit

    Example:
        try:
            with with_timeout(60, "Freerouting"):
                run_freerouting(circuit)
        except TimeoutError as e:
            logging.error(f"Freerouting timed out: {e}")
            # Handle timeout gracefully

    Note:
        - Only works on POSIX systems (Linux, macOS)
        - Uses SIGALRM signal (NOT thread-safe)
        - Timeout is approximate (within 1 second)
    """
    def signal_handler(signum, frame):
        """Signal handler for SIGALRM"""
        raise TimeoutError(f"{operation_name} exceeded {seconds}s timeout")

    # Save old handler
    old_handler = signal.signal(signal.SIGALRM, signal_handler)

    # Set alarm
    signal.alarm(seconds)

    try:
        yield
    finally:
        # Cancel alarm and restore old handler
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def with_timeout_decorator(seconds: int, operation_name: Optional[str] = None):
    """
    Decorator version of with_timeout

    Usage:
        @with_timeout_decorator(60, "Circuit conversion")
        def convert_circuit(circuit_file):
            ...

    Args:
        seconds: Maximum time allowed
        operation_name: Human-readable name (defaults to function name)

    Returns:
        Decorated function with timeout protection
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation_name or func.__name__
            with with_timeout(seconds, op_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


@contextmanager
def timed_operation(operation_name: str, log_level: int = logging.INFO):
    """
    Context manager for timing operations

    Usage:
        with timed_operation("Component placement"):
            place_components(...)
        # Automatically logs: "Component placement: 12.3s"

    Args:
        operation_name: Human-readable name
        log_level: Logging level (default: INFO)

    Example:
        with timed_operation("ERC validation", logging.DEBUG):
            run_erc(circuit)
    """
    start_time = time.time()
    logging.log(log_level, f"START: {operation_name}")

    try:
        yield
    finally:
        duration = time.time() - start_time
        logging.log(log_level, f"END: {operation_name} - {duration:.2f}s")


def log_function(func: Callable) -> Callable:
    """
    Decorator for automatic function logging

    Logs:
        - ENTER: function_name(args)
        - EXIT: function_name() - time=X.Xs
        - ERROR: function_name - exception

    Usage:
        @log_function
        def my_function(arg1, arg2):
            ...

    Example output:
        INFO: ENTER: place_component(component='R1', x=10, y=20)
        INFO: EXIT: place_component() - time=0.5s

    Or on error:
        INFO: ENTER: place_component(component='R1', x=10, y=20)
        ERROR: FAIL: place_component - ValueError: Invalid coordinates
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Build argument string (first 3 args + named args)
        args_repr = []
        for i, arg in enumerate(args[:3]):
            args_repr.append(f"arg{i}={repr(arg)[:50]}")
        for key, val in list(kwargs.items())[:3]:
            args_repr.append(f"{key}={repr(val)[:50]}")

        args_str = ", ".join(args_repr)
        if len(args) > 3 or len(kwargs) > 3:
            args_str += ", ..."

        # Log entry
        logging.info(f"ENTER: {func.__name__}({args_str})")

        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            logging.info(f"EXIT: {func.__name__}() - time={duration:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            logging.error(f"FAIL: {func.__name__} - {type(e).__name__}: {str(e)} (after {duration:.2f}s)")
            raise

    return wrapper


class PerformanceProfiler:
    """
    Simple performance profiler for identifying bottlenecks

    Usage:
        profiler = PerformanceProfiler()

        with profiler.measure("Component placement"):
            place_components(...)

        with profiler.measure("Routing"):
            route_board(...)

        profiler.report()  # Prints summary

    Output:
        === PERFORMANCE PROFILE ===
        Component placement: 12.3s (45%)
        Routing: 15.1s (55%)
        TOTAL: 27.4s
    """

    def __init__(self):
        """Initialize profiler"""
        self.measurements = {}
        self.total_time = 0.0

    @contextmanager
    def measure(self, operation_name: str):
        """Measure time for an operation"""
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            if operation_name not in self.measurements:
                self.measurements[operation_name] = 0.0
            self.measurements[operation_name] += duration
            self.total_time += duration

    def report(self, log_level: int = logging.INFO):
        """Print performance report"""
        if self.total_time == 0:
            logging.log(log_level, "=== PERFORMANCE PROFILE ===\nNo measurements recorded")
            return

        logging.log(log_level, "=== PERFORMANCE PROFILE ===")

        # Sort by time (descending)
        sorted_ops = sorted(self.measurements.items(), key=lambda x: x[1], reverse=True)

        for operation, duration in sorted_ops:
            percentage = (duration / self.total_time) * 100
            logging.log(log_level, f"{operation}: {duration:.1f}s ({percentage:.0f}%)")

        logging.log(log_level, f"TOTAL: {self.total_time:.1f}s")

    def reset(self):
        """Reset all measurements"""
        self.measurements.clear()
        self.total_time = 0.0


def calculate_adaptive_timeout(
    num_components: int,
    num_nets: int,
    base_seconds: int = 30,
    component_factor: float = 1.0,
    net_factor: float = 0.5,
    min_timeout: int = 30,
    max_timeout: int = 120
) -> int:
    """
    Calculate timeout based on circuit complexity (GENERIC)

    Formula: base + (components × factor) + (nets × factor)
    Clamped: min_timeout <= result <= max_timeout

    Args:
        num_components: Number of components in circuit
        num_nets: Number of nets in circuit
        base_seconds: Base overhead (file I/O, setup)
        component_factor: Seconds per component (default: 1s)
        net_factor: Seconds per net (default: 0.5s)
        min_timeout: Minimum timeout (default: 30s)
        max_timeout: Maximum timeout (default: 120s = 2min)

    Returns:
        Timeout in seconds (int)

    Examples:
        # Simple circuit (5 components, 10 nets)
        calculate_adaptive_timeout(5, 10)
        # = 30 + 5*1 + 10*0.5 = 40s

        # Medium circuit (30 components, 80 nets)
        calculate_adaptive_timeout(30, 80)
        # = 30 + 30*1 + 80*0.5 = 100s

        # Complex circuit (100 components, 300 nets)
        calculate_adaptive_timeout(100, 300)
        # = 30 + 100*1 + 300*0.5 = 280s → capped at 120s

    GENERIC DESIGN:
        Works for ANY circuit complexity without hardcoding
    """
    # Calculate raw timeout
    timeout = base_seconds + (num_components * component_factor) + (num_nets * net_factor)

    # Clamp to reasonable range
    timeout = max(min_timeout, min(max_timeout, timeout))

    return int(timeout)


# Example usage and test
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("=== TIMEOUT MANAGER TESTS ===\n")

    # Test 1: Basic timeout
    print("Test 1: Timeout context manager")
    try:
        with with_timeout(2, "Test operation"):
            print("  Starting 1-second operation...")
            time.sleep(1)
            print("  ✓ Completed within timeout")
    except TimeoutError as e:
        print(f"  ✗ {e}")

    # Test 2: Timeout exceeded
    print("\nTest 2: Timeout exceeded")
    try:
        with with_timeout(1, "Long operation"):
            print("  Starting 2-second operation...")
            time.sleep(2)
            print("  This shouldn't print")
    except TimeoutError as e:
        print(f"  ✓ Caught timeout: {e}")

    # Test 3: Timed operation
    print("\nTest 3: Timed operation")
    with timed_operation("Example task"):
        time.sleep(0.5)

    # Test 4: Function logging
    print("\nTest 4: Function logging")
    @log_function
    def example_function(x, y):
        return x + y

    result = example_function(10, 20)
    print(f"  Result: {result}")

    # Test 5: Performance profiler
    print("\nTest 5: Performance profiler")
    profiler = PerformanceProfiler()

    with profiler.measure("Task A"):
        time.sleep(0.3)

    with profiler.measure("Task B"):
        time.sleep(0.5)

    with profiler.measure("Task A"):  # Add more time to Task A
        time.sleep(0.2)

    profiler.report()

    # Test 6: Adaptive timeout calculation
    print("\nTest 6: Adaptive timeout")
    circuits = [
        (5, 10, "Simple"),
        (30, 80, "Medium"),
        (100, 300, "Complex")
    ]

    for comps, nets, name in circuits:
        timeout = calculate_adaptive_timeout(comps, nets)
        print(f"  {name} ({comps} comps, {nets} nets): {timeout}s timeout")

    print("\n✅ All tests complete!")
