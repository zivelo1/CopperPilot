# Test Suite Documentation

**Last Updated**: October 27, 2025
**Test Framework**: Pytest
**Total Production Tests**: 26 scripts

---

## Quick Start

### Run All Tests
```bash
# Run full test suite
pytest

# Run with verbose output
pytest -v

# Run specific test
pytest tests/test_kicad_converter.py -v
```

### Run By Category
```bash
# Quick smoke tests (skip slow forensic tests)
pytest -m "not deep" -v

# Only converter tests
pytest -m "converter" -v

# Only deep forensic validation
pytest -m "deep" -v
```

### Backwards Compatibility
```bash
# Old script-style execution still works
python tests/test_kicad_converter.py
python tests/run_all_converter_tests.py
```

---

## Test Categories

### 1. Converter Tests (6 tests) - `@pytest.mark.converter`

Production-critical tests that validate each converter:

| Test | Converter | Duration | What It Tests |
|------|-----------|----------|---------------|
| `test_kicad_converter.py` | KiCad | ~2 min | ERC/DRC validation, file format |
| `test_eagle_converter.py` | Eagle | ~2 min | XML validation, geometric accuracy |
| `test_easyeda_pro_converter.py` | EasyEDA Pro | ~1 min | JSON format, import readiness |
| `test_bom_converter.py` | BOM | ~30s | CSV/XLSX generation, dual-supplier |
| `test_schematics_converter.py` | Schematics | ~1 min | PNG generation, image validity |
| `test_schematics_text_converter.py` | Schematics Text | ~30s | Text descriptions, readability |

**Usage:**
```bash
# Run all converter tests
pytest -m "converter" -v

# Run specific converter
pytest tests/test_kicad_converter.py -v
```

---

### 2. Core Validators (8 scripts) - MANDATORY

Critical validation scripts used in Step 5 QA and extensively documented:

#### Primary Validators

**`analyze_lowlevel_circuits.py`** ⭐ **MOST IMPORTANT**
- **Purpose**: Comprehensive lowlevel circuit validator (8 checks)
- **Used By**: Step 5 QA, multiple docs
- **References**: 35+ across codebase
- **Usage**:
  ```bash
  python tests/analyze_lowlevel_circuits.py output/[UNIQUE_ID]/lowlevel
  ```

**`validate_kicad_forensic.py`**
- **Purpose**: KiCad ERC/DRC forensic validator
- **Used By**: Step 5 QA, deep validation wrappers
- **Usage**:
  ```bash
  python tests/validate_kicad_forensic.py output/[ID]/kicad
  ```

**`validate_eagle_comprehensive.py`**
- **Purpose**: Eagle geometric accuracy + 10 structural tests
- **Used By**: Step 5 QA, TESTING_GUIDE.md
- **Usage**:
  ```bash
  python tests/validate_eagle_comprehensive.py output/[ID]/eagle
  ```

**`validate_easyeda_pro_forensic.py`**
- **Purpose**: EasyEDA Pro import readiness
- **Used By**: Step 5 QA
- **Usage**:
  ```bash
  python tests/validate_easyeda_pro_forensic.py output/[ID]/easyeda_pro
  ```

#### Secondary Validators

- `validate_eagle_files.py` - Eagle structural checks (supplement to comprehensive)
- `validate_ratsnest.py` - KiCad ratsnest sanity check
- `validate_lowlevel_circuits.py` - Secondary lowlevel validator (backup)
- `run_all_converter_tests.py` - Master test runner (orchestrates all 6 converter tests)

---

### 3. Simulation Utilities (6 scripts) - NEW (Oct 27, 2025)

Quick converter-only testing: clean → run → basic validation

| Script | Converter | What It Does |
|--------|-----------|--------------|
| `simulate_kicad_conversion.py` | KiCad | Clean kicad/ → run converter |
| `simulate_eagle_conversion.py` | Eagle | Clean eagle/ → run converter |
| `simulate_easyeda_pro_conversion.py` | EasyEDA Pro | Clean easyeda_pro/ → run converter |
| `simulate_schematics_conversion.py` | Schematics | Clean schematics/ → run converter |
| `simulate_schematics_desc_conversion.py` | Schematics Text | Clean schematics_text/ → run converter |
| `simulate_step3_from_ai_output.py` | Step 3 | Run Step 3 from AI output directly |

**Usage Pattern:**
```bash
# Quick conversion test
python tests/simulate_kicad_conversion.py
```

**Purpose**: Fast, repeatable conversion testing without touching other outputs.

---

### 4. Deep Validation Wrappers (5 scripts) - NEW (Oct 27, 2025)

Comprehensive validation: preflight + deep forensic checks

| Script | What It Validates |
|--------|-------------------|
| `validate_kicad_deep_forensic.py` | Preflight + validate_kicad_forensic.py |
| `validate_eagle_deep_forensic.py` | Preflight + validate_eagle_comprehensive.py |
| `validate_easyeda_pro_deep_forensic.py` | Preflight + validate_easyeda_pro_forensic.py |
| `validate_schematics_deep_forensic.py` | PNG coverage + size checks |
| `validate_schematics_desc_deep_forensic.py` | Text coverage + content heuristics |

**Usage Pattern:**
```bash
# After simulation, validate deeply
python tests/validate_kicad_deep_forensic.py
```

**Recommended Workflow:**
```bash
# 1. Simulate conversion
python tests/simulate_kicad_conversion.py

# 2. Validate deeply
python tests/validate_kicad_deep_forensic.py
```

---

### 5. Step Simulation Tests (2 scripts)

Workflow step testing:

- `test_step2_simulation.py` - Step 2 high-level design testing
- `test_step3_simulation.py` - Step 3 lowlevel circuit testing

**Usage:**
```bash
pytest tests/test_step2_simulation.py -v
pytest tests/test_step3_simulation.py -v
```

---

## Archived Tests

14 legacy test scripts were moved to `tests/archive/` during October 2025 cleanup:

- **`step3_redundant/`** (4 files) - Superseded by newer simulation scripts
- **`manual_tools/`** (3 files) - Manual fix tools no longer needed
- **`legacy_validators/`** (4 files) - Replaced by comprehensive validators
- **`old_integration/`** (3 files) - Replaced by targeted converter tests

See `tests/archive/README.md` for details and restoration instructions.

---

## Common Testing Workflows

### For Developers (Daily Testing)

**Quick Smoke Test** (2 minutes)
```bash
pytest -m "not deep" -v
```

**Test Specific Converter After Changes**
```bash
pytest tests/test_kicad_converter.py -v
```

**Simulate + Validate Pattern** (Recommended)
```bash
# Example: KiCad converter
python tests/simulate_kicad_conversion.py
python tests/validate_kicad_deep_forensic.py
```

### For CI/CD (Automated)

**PR Validation** (fast, fail-fast)
```bash
pytest -m "not deep" --maxfail=3
```

**Nightly Deep Validation**
```bash
pytest -m "deep" -v --tb=long
```

### For Release (Full Validation)

**Complete Test Suite**
```bash
# 1. Run all converter tests
python tests/run_all_converter_tests.py

# 2. Run pytest suite
pytest -v --tb=long

# 3. Validate lowlevel circuits
python tests/analyze_lowlevel_circuits.py output/[latest]/lowlevel

# 4. Deep forensic validation
python tests/validate_kicad_deep_forensic.py
python tests/validate_eagle_deep_forensic.py
python tests/validate_easyeda_pro_deep_forensic.py
```

---

## Pytest Features

### Markers

Tests are categorized with pytest markers for flexible execution:

```python
@pytest.mark.converter  # Converter tests (6 tests)
@pytest.mark.validator  # Validation tests
@pytest.mark.simulation # Simulation tests (quick)
@pytest.mark.deep       # Deep forensic tests (slow)
@pytest.mark.integration # Full workflow tests
```

**Usage:**
```bash
# Run only converter tests
pytest -m "converter"

# Skip deep/slow tests
pytest -m "not deep"

# Run multiple categories
pytest -m "converter or simulation"
```

### Fixtures

Shared test fixtures in `conftest.py`:

- `base_output_dir` - Base output directory
- `latest_output_folder` - Auto-detected latest run
- `lowlevel_dir` - Lowlevel circuit directory
- `kicad_output_dir` - KiCad output (auto-cleaned)
- `eagle_output_dir` - Eagle output (auto-cleaned)
- `easyeda_output_dir` - EasyEDA Pro output (auto-cleaned)
- `bom_output_dir` - BOM output (auto-cleaned)
- `schematics_output_dir` - Schematics output (auto-cleaned)
- `schematics_desc_output_dir` - Schematics text output (auto-cleaned)

---

## Configuration

### pytest.ini

Location: `/pytest.ini` (project root)

Key settings:
- Markers defined for test categorization
- Verbose output by default
- 10-minute timeout per test
- Archive and integration folders excluded
- Short traceback format for cleaner output

### conftest.py

Location: `/tests/conftest.py`

Provides:
- Shared fixtures for all tests
- Auto-detection of latest output folder
- Auto-cleaning of output directories before tests
- Pytest marker configuration

---

## Troubleshooting

### Test Fails with "No output directories found"

**Cause**: No `output/[UNIQUE_ID]/` folders exist.

**Solution**: Run a full workflow first to generate test data:
```bash
python main.py "Design a simple LED circuit"
```

### Tests Can't Find Scripts

**Cause**: Python path not set correctly.

**Solution**: Run from project root:
```bash
cd /path/to/Electronics
pytest tests/test_kicad_converter.py
```

### Converter Test Times Out

**Cause**: Complex circuits or slow system.

**Solution**: Increase timeout in pytest.ini:
```ini
timeout = 1200  # 20 minutes
```

### Want to Run Archived Test

**Solution**: Copy from archive:
```bash
cp tests/archive/[category]/[script].py tests/
python tests/[script].py
```

---

## Development

### Adding a New Test

1. Create test file: `test_my_feature.py`
2. Add pytest marker if needed
3. Use fixtures from `conftest.py`
4. Follow naming convention: `test_*`

Example:
```python
import pytest

@pytest.mark.converter
def test_my_converter(lowlevel_dir, my_output_dir):
    """Test my converter"""
    # Test implementation
    assert True
```

### Running Tests During Development

```bash
# Run single test function
pytest tests/test_kicad_converter.py::test_kicad_converter -v

# Run with print statements visible
pytest tests/test_kicad_converter.py -v -s

# Stop on first failure
pytest --maxfail=1

# Show local variables on failure
pytest --showlocals
```

---

## See Also

- **`tests/TESTING_STRATEGY.md`** - Testing philosophy and strategy
- **`tests/archive/README.md`** - Archived test documentation
- **`docs/TESTING_GUIDE.md`** - Unified testing guide (quick + deep)
- **`pytest.ini`** - Pytest configuration

---

**Maintained by**: Electronics Project Team
**Test Suite Version**: 2.0 (October 2025 Modernization)
**Framework**: Pytest 7.x+
