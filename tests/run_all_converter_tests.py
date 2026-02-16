#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Master Test Runner - Run all 7 converter tests
Each test: Clean → Run → Deep Validate (ERC/DRC equivalent)
"""

import sys
import subprocess
from pathlib import Path
import time

def run_test(test_script: str) -> bool:
    """Run a single test script"""
    script_path = Path(__file__).parent / test_script

    print(f"\n{'='*80}")
    print(f"RUNNING: {test_script}")
    print(f"{'='*80}\n")

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            timeout=600  # 10 minutes per test
        )

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        print(f"\n❌ {test_script} - TIMEOUT")
        return False
    except Exception as e:
        print(f"\n❌ {test_script} - ERROR: {e}")
        return False

def main():
    """Run all converter tests"""

    print("="*80)
    print("MASTER CONVERTER TEST RUNNER")
    print("="*80)
    print("\nRunning all 6 converter tests with deep validation (ERC/DRC)")
    print("Each test: Clean → Run → Validate\n")

    start_time = time.time()

    # All test scripts
    tests = [
        "test_bom_converter.py",
        "test_eagle_converter.py",
        "test_kicad_converter.py",
        "test_easyeda_pro_converter.py",
        "test_schematics_converter.py",
        "test_schematics_text_converter.py",
    ]

    results = {}

    for test_script in tests:
        success = run_test(test_script)
        results[test_script] = success
        time.sleep(1)  # Brief pause between tests

    elapsed = time.time() - start_time

    # Summary
    print(f"\n{'='*80}")
    print("TEST SUITE SUMMARY")
    print(f"{'='*80}")
    print(f"Total time: {elapsed:.1f}s\n")

    passed_count = sum(1 for r in results.values() if r)
    failed_count = len(results) - passed_count

    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        converter_name = test_name.replace("test_", "").replace("_converter.py", "").replace("_", " ").title()
        print(f"{status}: {converter_name}")

    print(f"\n{'='*80}")
    print(f"Results: {passed_count}/{len(results)} tests passed")
    print(f"{'='*80}")

    if failed_count == 0:
        print("\n🎉 ALL CONVERTER TESTS PASSED - 100% SUCCESS")
        print("\nAll converters are:")
        print("  ✅ Processing perfect lowlevel circuits correctly")
        print("  ✅ Generating valid output files")
        print("  ✅ Passing ERC/DRC validation")
        print("  ✅ Ready for PCB manufacturing")
        return True
    else:
        print(f"\n❌ {failed_count} CONVERTER TEST(S) FAILED")
        print("\nAction required:")
        print("  1. Review failed test output above")
        print("  2. Analyze root cause (lowlevel data vs script)")
        print("  3. Fix issues")
        print("  4. Re-run: python tests/run_all_converter_tests.py")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)