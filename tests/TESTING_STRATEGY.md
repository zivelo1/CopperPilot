# Testing Strategy

**Last Updated**: October 27, 2025
**Version**: 2.0 (Post-Modernization)

---

## Philosophy

### Core Principles

1. **Fail-Closed Quality Gates** - Bad outputs are deleted, never released
2. **Real Validation** - Use actual ERC/DRC tools, not simulated checks
3. **Automated Testing** - Minimize manual intervention
4. **Fast Feedback** - Quick smoke tests for development, deep validation for releases
5. **Maintainability** - Clear structure, well-documented, easy to understand

### Testing Pyramid

```
        /\
       /  \      End-to-End (Manual)
      /____\
     /      \    Integration Tests (Converters)
    /________\
   /          \  Unit Tests (Validators)
  /____________\
```

**Bottom Layer (Unit)**: Fast, focused validators
- `analyze_lowlevel_circuits.py` - Lowlevel structure validation
- Individual file format validators
- **Run time**: <10s each
- **Run frequency**: Every code change

**Middle Layer (Integration)**: Converter tests
- 6 converter tests (KiCad, Eagle, EasyEDA Pro, BOM, Schematics, Schematics Text)
- **Run time**: 30s - 2min each
- **Run frequency**: Before commit, in CI

**Top Layer (End-to-End)**: Full workflow validation
- Step 5 QA/QC orchestration
- Manual verification of final outputs
- **Run time**: 5-10 min
- **Run frequency**: Before release

---

## Test Categories

### 1. Converter Tests (`@pytest.mark.converter`)

**Purpose**: Validate that converters transform lowlevel circuits to target formats correctly.

**Pattern**: Clean → Run → Validate
```python
@pytest.mark.converter
def test_kicad_converter(lowlevel_dir, kicad_output_dir):
    # 1. Output dir cleaned automatically (fixture)
    # 2. Run converter
    assert run_converter(lowlevel_dir, kicad_output_dir)
    # 3. Validate outputs
    assert validate_outputs(kicad_output_dir)
```

**When to Run**:
- ✅ After changing converter code
- ✅ Before committing converter changes
- ✅ In CI on every PR

**Expected Duration**: 30s - 2min per converter

---

### 2. Validators (No pytest marker)

**Purpose**: Deep forensic validation of generated files.

**Types**:

**A. Lowlevel Validators**
- `analyze_lowlevel_circuits.py` - **MOST CRITICAL**
- Runs 8 comprehensive checks
- Validates circuit structure, connectivity, completeness

**B. Format-Specific Validators**
- `validate_kicad_forensic.py` - KiCad ERC/DRC
- `validate_eagle_comprehensive.py` - Eagle geometric + structural
- `validate_easyeda_pro_forensic.py` - EasyEDA Pro import readiness

**C. Deep Validation Wrappers** (NEW)
- Preflight checks + primary validator
- `validate_kicad_deep_forensic.py`
- `validate_eagle_deep_forensic.py`
- `validate_easyeda_pro_deep_forensic.py`
- `validate_schematics_deep_forensic.py`
- `validate_schematics_desc_deep_forensic.py`

**When to Run**:
- ✅ After converter execution
- ✅ Before release
- ✅ When investigating issues

---

### 3. Simulation Utilities (No pytest marker)

**Purpose**: Quick, repeatable conversion testing without full workflow.

**Pattern**: Find latest → Clean → Convert
```bash
python tests/simulate_kicad_conversion.py
```

**When to Run**:
- ✅ During converter development
- ✅ Quick validation after changes
- ✅ Debugging specific converter issues

**Expected Duration**: 30s - 1min

**Best Practice**: Pair with deep validation
```bash
# 1. Simulate
python tests/simulate_kicad_conversion.py

# 2. Validate
python tests/validate_kicad_deep_forensic.py
```

---

## Testing Workflows

### Daily Development

**Goal**: Fast feedback during active development

```bash
# Quick smoke test (skip slow forensic tests)
pytest -m "not deep" -v

# Test specific component
pytest tests/test_kicad_converter.py -v

# Or use simulation utility
python tests/simulate_kicad_conversion.py
```

**Duration**: 2-5 minutes
**Frequency**: Multiple times per day

---

### Pre-Commit

**Goal**: Ensure code changes don't break converters

```bash
# Run all converter tests
pytest -m "converter" -v

# Or use master runner
python tests/run_all_converter_tests.py
```

**Duration**: 6-12 minutes (all 6 converters)
**Frequency**: Before every commit

---

### CI/CD Pipeline

**Goal**: Automated validation on every PR

**Fast Track** (PR validation):
```bash
pytest -m "not deep" --maxfail=3 -v
```
- Runs converter tests only
- Fails fast on first 3 failures
- **Duration**: 6-12 minutes

**Deep Track** (Nightly):
```bash
pytest -m "deep" -v --tb=long
```
- Runs all forensic validators
- Full traceback on failures
- **Duration**: 15-30 minutes

---

### Pre-Release

**Goal**: Comprehensive validation before release

**Full Test Suite**:
```bash
# 1. Master converter test runner
python tests/run_all_converter_tests.py

# 2. Full pytest suite
pytest -v --tb=long

# 3. Lowlevel circuit analysis
python tests/analyze_lowlevel_circuits.py output/[latest]/lowlevel

# 4. Deep forensic validation (all converters)
python tests/validate_kicad_deep_forensic.py
python tests/validate_eagle_deep_forensic.py
python tests/validate_easyeda_pro_deep_forensic.py
python tests/validate_schematics_deep_forensic.py
python tests/validate_schematics_desc_deep_forensic.py

# 5. Step 5 QA/QC (manual review)
# Review reports in output/[latest]/verification/
```

**Duration**: 20-30 minutes
**Frequency**: Before every release

---

## Quality Gates

### What are Quality Gates?

**Definition**: Automated checkpoints that prevent bad outputs from proceeding.

**Implementation**: Converters delete imperfect files and raise exceptions.

### Example: KiCad Quality Gate

```python
# After ERC/DRC validation
if erc_errors > 0 or drc_errors > 0:
    print(f"🚫 QUALITY GATE: Circuit FAILED with {total_errors} errors")
    print(f"🗑️  Deleting imperfect files (FAIL-CLOSED)...")

    # Delete ALL files
    for file in [pro_file, sch_file, pcb_file]:
        if file.exists():
            file.unlink()

    # Raise exception to stop processing
    raise RuntimeError(f"Circuit FAILED validation with {total_errors} errors")
```

### Quality Gate Guarantees

1. **Never Release Bad Files** - Imperfect outputs are deleted
2. **Fail-Closed** - System fails safe (no output better than bad output)
3. **Clear Feedback** - Errors clearly reported with file locations
4. **Traceable** - ERC/DRC reports saved for debugging

---

## Test Data Management

### Input Data (Lowlevel Circuits)

**Source**: Generated by Step 3 (Low-Level Design)
**Location**: `output/[UNIQUE_ID]/lowlevel/`
**Format**: JSON files (`circuit_*.json`)

**Quality Requirements**:
- ✅ Valid JSON structure
- ✅ All required fields present
- ✅ Components have pins
- ✅ Connections reference valid pins
- ✅ Validated by `analyze_lowlevel_circuits.py`

### Output Data (Converter Results)

**Location**: `output/[UNIQUE_ID]/[converter_name]/`

**Formats**:
- KiCad: `.kicad_sch`, `.kicad_pcb`, `.kicad_pro`
- Eagle: `.sch`, `.brd`
- EasyEDA Pro: `.json`
- BOM: `.csv`, `.xlsx`
- Schematics: `.png`
- Schematics Text: `.txt`

### Verification Data (Validation Results)

**Location**: `output/[UNIQUE_ID]/verification/` ← **NEW STRUCTURE**

**Contents**:
```
verification/
├── kicad/
│   ├── erc/              ← ERC reports
│   ├── drc/              ← DRC reports
│   └── forensic/         ← Forensic analysis
├── eagle/
│   ├── erc/
│   ├── drc/
│   └── forensic/
├── lowlevel/
│   └── analysis/         ← Circuit analysis reports
├── step5_qa/             ← QA/QC reports
└── logs/                 ← Test execution logs
```

**Purpose**:
- Not shown to user
- Used by Step 5 QA/QC
- Historical validation records
- Debugging and troubleshooting

---

## Failure Handling

### Converter Failures

**Symptoms**:
- Converter script exits with non-zero code
- No output files generated
- Python exception raised

**Debugging Steps**:
1. Check converter stdout/stderr
2. Validate input data with `analyze_lowlevel_circuits.py`
3. Run converter with verbose logging
4. Check for missing dependencies

**Example**:
```bash
# Validate input first
python tests/analyze_lowlevel_circuits.py output/[ID]/lowlevel

# Run converter with debug
python scripts/kicad_converter.py output/[ID]/lowlevel output/[ID]/kicad
```

### Validation Failures

**Symptoms**:
- Files generated but validation reports errors
- ERC/DRC reports contain violations
- Quality gate deletes files

**Debugging Steps**:
1. Read ERC/DRC reports in `verification/`
2. Open files in target tool (KiCad, Eagle, etc.)
3. Identify root cause (converter bug vs input data issue)
4. Fix and re-run

**Example**:
```bash
# Check ERC reports
cat output/[ID]/verification/kicad/erc/*.erc.rpt

# Re-run deep forensic validation
python tests/validate_kicad_deep_forensic.py
```

---

## Pytest Integration

### Why Pytest?

**Benefits**:
1. **Better organization** - Fixtures, markers, parametrization
2. **Parallel execution** - Run tests concurrently (future)
3. **Better reporting** - Clear pass/fail, detailed failures
4. **Industry standard** - Widely used, well-documented
5. **Extensible** - Plugins for coverage, profiling, etc.

### Markers

Tests are categorized for selective execution:

```python
@pytest.mark.converter  # Converter tests (6 tests)
@pytest.mark.validator  # Validation tests
@pytest.mark.simulation # Simulation tests (quick)
@pytest.mark.deep       # Deep forensic tests (slow)
```

**Usage**:
```bash
# Run only converters
pytest -m "converter"

# Skip slow tests
pytest -m "not deep"

# Combine markers
pytest -m "converter or simulation"
```

### Fixtures

Shared test setup/teardown in `conftest.py`:

```python
@pytest.fixture
def kicad_output_dir(latest_output_folder):
    """Auto-cleaned KiCad output directory"""
    output_dir = latest_output_folder / "kicad"
    _clean_output_folder(output_dir)
    yield output_dir
    # Cleanup after test (if needed)
```

**Benefits**:
- No manual cleanup in tests
- Consistent test isolation
- Reusable across tests

---

## Backwards Compatibility

### Script-Style Execution Still Works

All tests can run standalone:

```bash
# Pytest style (new)
pytest tests/test_kicad_converter.py -v

# Script style (still works)
python tests/test_kicad_converter.py
```

### Migration Path

**Phase 1** (COMPLETE): Convert to pytest format
- ✅ Add pytest markers
- ✅ Use fixtures
- ✅ Keep script-style main() for compatibility

**Phase 2** (Future): Migrate all scripts
- Convert validators to pytest
- Add unit tests for utilities
- Achieve >80% code coverage

**Phase 3** (Future): Advanced features
- Parallel test execution
- Coverage reporting
- Performance benchmarking

---

## Maintenance

### Adding New Tests

**Converter Test**:
1. Create `test_my_converter.py`
2. Add to `conftest.py` fixtures if needed
3. Add `@pytest.mark.converter`
4. Follow pattern: clean → run → validate

**Validator**:
1. Create `validate_my_format.py`
2. Follow forensic validation pattern
3. Save reports to `verification/`
4. Document in `tests/README.md`

### Updating Existing Tests

**When converter changes**:
1. Update test expectations if needed
2. Run full test suite to catch regressions
3. Update documentation if test behavior changes

**When adding features**:
1. Add test coverage for new feature
2. Ensure existing tests still pass
3. Update validation if output format changes

### Archive Policy

**When to archive**:
- Test superseded by newer approach
- Functionality covered by other tests
- No longer referenced in docs or code

**How to archive**:
1. Move to `tests/archive/[category]/`
2. Document reason in `tests/archive/README.md`
3. Update `tests/README.md` to remove reference
4. Keep for historical reference (don't delete)

---

## Best Practices

### DO ✅

- Run validators on actual generated files
- Use quality gates to prevent bad outputs
- Test with real workflow outputs (not synthetic data)
- Keep tests fast (use markers for slow tests)
- Document test purpose and usage
- Clean output folders before tests
- Use fixtures for common setup

### DON'T ❌

- Skip validation steps (always validate outputs)
- Test with fake/mock data instead of real circuits
- Hardcode paths or file names
- Leave test outputs in repository
- Disable quality gates (even temporarily)
- Run tests without cleaning output first
- Mix test data with production data

---

## Metrics

### Test Coverage Goals

- **Converter coverage**: 100% (all 6 converters tested)
- **Validator coverage**: 100% (all validators tested)
- **Critical path coverage**: 100% (Step 3 → Converters → Validation)
- **Code coverage** (future): >80% of converter scripts

### Performance Targets

- **Quick smoke test**: <5 minutes
- **Full converter suite**: <15 minutes
- **Deep validation**: <30 minutes
- **Pre-release validation**: <45 minutes

### Quality Metrics

- **ERC errors**: 0 (mandatory)
- **DRC violations**: 0 (mandatory)
- **Geometric accuracy**: >95% (Eagle)
- **File validity**: 100% (all formats)

---

## Troubleshooting

### Common Issues

**"No output directories found"**
→ Run workflow first: `python main.py "Design LED circuit"`

**"Converter test timeout"**
→ Increase timeout in `pytest.ini`: `timeout = 1200`

**"Import error: No module named pytest"**
→ Install pytest: `pip install pytest`

**"Fixture not found"**
→ Check `tests/conftest.py` exists and is correct

**"Archived test needed"**
→ Copy from `tests/archive/`: `cp tests/archive/[category]/[test].py tests/`

---

## See Also

- **`tests/README.md`** - Test documentation and usage
- **`tests/archive/README.md`** - Archived tests documentation
- **`docs/TESTING_GUIDE.md`** - Unified testing guide (quick + deep)
- **`pytest.ini`** - Pytest configuration
- **`tests/conftest.py`** - Shared fixtures

---

**Maintained by**: Electronics Project Team
**Strategy Version**: 2.0
**Last Review**: October 27, 2025
