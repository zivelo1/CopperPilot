# Unified Testing Guide (Quick + Complete)

This document consolidates the previous “TESTING_GUIDE.md” (quick reference) and “COMPLETE_TEST_GUIDE.md” (full guide). It provides a single source for fast workflows and deep, production‑grade validation across KiCad, Eagle, and EasyEDA outputs.

---

## Quick Start (Most Common)

- Activate venv and run the deep validators for latest outputs:
  - KiCad: `python tests/validate_kicad_deep_forensic.py`
  - Eagle: `python tests/validate_eagle_deep_forensic.py`
  - EasyEDA Pro: `python tests/validate_easyeda_pro_deep_forensic.py`

- **Production Signoff (Master Audit)**:
  - `python tests/production_signoff.py --run-id <run-id>`
  - Audits a run against all 6 forensic acceptance criteria (Interface closure, ERC/DRC, Rating compliance, SPICE reliability, Component parity, and Taxonomy integrity).

- Deterministic Step‑3 replay (optional):
  - `python tests/simulate_step3_from_ai_output.py --run-id <run>`
  - `python tests/analyze_lowlevel_circuits.py output/<run>/lowlevel`

- Success gate (generic): ERC=0, DRC=0, and all eight forensic checks pass. Treat any error as fail‑closed until fixed.

- Circuit supervisor convergence behavior (all thresholds configurable via `server/config.py` QUALITY_GATES):
  - `max_supervisor_iterations` (default 10) — maximum fix loop iterations
  - `max_stall_iterations` (default 3) — exits early when fixers stop improving
  - `max_fixer_iterations` (default 3) — maximum circuit fixer iterations per module
  - `voltage_derating_factor` (default 1.2) — component voltage rating safety margin
  - `min_ground_connection_ratio` (default 0.05) — minimum ground coverage
  - `max_critical_fixer_issues` (default 0) — hard gate for critical issue count
  - Interface nets (SPI_, I2C_, UART_, etc.) are classified as warnings, not errors
  - Rating violations are validated per-module voltage domain (not blanket system max)
  - Integration agent signal matching: Strategy 5 removed, suffix/contains thresholds configurable
  - `circuit_integrated_circuit.json` (mega-module) is no longer generated

- Config-centralized patterns — all pattern sets live in `server/config.py` with zero duplication across consumers. Key config categories include:
  - **Component classification**: `ACTIVE_COMPONENT_TYPES`, `NON_ACTIVE_COMPONENT_TYPES` (36 types), `SEMANTIC_TAXONOMY`, `TWO_PIN_PASSIVE_TYPES`, `VOLTAGE_RATED_TYPES`
  - **Pattern matching**: `INTERFACE_NET_PATTERNS` (100+ patterns), `POWER_RAIL_PREFIXES/EXACT/PATTERNS`, `SINGLE_ENDED_EXEMPT_PATTERNS`, `SUPERVISOR_GPIO_PATTERNS`
  - **SPICE**: `SPICE_PIN_NAME_ALIASES`, `BEHAVIORAL_MODEL_PIN_MAP` (13 ICs), `SPICE_POWER_SOURCE_PATTERNS`, `SPICE_GROUND_PATTERNS`, `SPICE_VALUE_TYPE_DESCRIPTORS`, `SPICE_SUBCIRCUIT_OUTPUT_PIN_NAMES`
  - **Integration**: `INTEGRATION_HARDWARE_PREFIXES_TO_STRIP` (17 entries), `INTERFACE_MODULE_PREFIXES`, `EXTERNAL_INPUT_NET_PATTERNS`, `INTEGRATION_SIGNAL_SUFFIXES`
  - **Quality gates**: `FEEDBACK_DIVIDER_TOLERANCE`, `FEEDBACK_PIN_NAMES`, `FLOATING_INPUT_KEYWORDS`, `CONFIG_PIN_KEYWORDS`, `SUPERVISOR_POWER_PIN_NAMES`
  - **Misc**: `OPTOCOUPLER_PART_PATTERNS`, `UNICODE_SANITIZE_MAP`, `CONNECTOR_REF_PREFIXES`, `TESTPOINT_REF_PREFIXES`
  - Component ratings DB: 177 entries in `data/component_ratings.json`
  - All quality gate defaults are fail-closed (`fixer_gate_passed=False`, `integration_gate_passed=False`)

- Validated quality thresholds:
  - Supervisor false positive rate: **<5%** (down from ~70% baseline)
  - SPICE: B-source syntax validated, pin ordering corrected, power sources match suffixed nets, voltage source loops prevented
  - Interface signal matching: **>95%** (up from ~60%)
  - Note: AI-generated output is non-deterministic — results vary between runs

- Issue severity classification (configured in `config.ISSUE_SEVERITY`):
  - CRITICAL: `shorted_passives`, `phantom_component`, `missing_components`, `missing_pinNetMapping`
  - HIGH: `power_connections`, `invalid_pin`, `wrong_connection_format`
  - MEDIUM: `floating_components`, `pin_mismatches`, `net_conflicts`, `insufficient_connection_points`
  - LOW: `single_ended_nets`, `missing_connections`
  - ERC results now include `severity_counts` breakdown in return dict

- Integration Agent and cross-module connectivity:
  - SYS_ prefix for cross-module nets (configurable via `SYS_NET_PREFIX` env var)
  - Power/ground rails keep original names (not wrapped in SYS_ prefix)
  - Integration Agent uses `module_prefix_map` to correctly prefix pin references
  - Double supervisor execution removed (supervisor runs once, not twice)
  - `_build_interface_net_map()` uses direct signal map from Integration Agent as primary source

- Connection Agent validation:
  - `_remove_phantom_references()` validates all pin refs against component list
  - `_warn_dangling_internal_nets()` detects single-connection internal nets
  - `_fix_pin_reference_nets()` renames pin-reference net names (LAW 5 enforcement)
  - Dynamic power/ground rail detection via `_detect_power_rail()` / `_detect_ground_rail()`

---

## Complete Test Guide for Circuit Generation System

## Overview
This guide provides step-by-step instructions for thoroughly testing the circuit generation system to ensure it produces PERFECT results.

**STATUS**: Under active development. Quality varies by circuit complexity — see `QUALITY_BASELINE.md` for current metrics.

### Latest Benchmark Results:
- **Simple circuits** (e.g., Buck 12V-to-5V, 3 modules): **3/3 PERFECT**, 0 remaining fixer issues
- **Complex circuits** (e.g., US Amplifier, 7 modules): **7/7 PERFECT** (best run), 0 remaining fixer issues
- Quality varies by circuit complexity and AI non-determinism — see `QUALITY_BASELINE.md` for detailed metrics
- All circuits require professional engineering review before fabrication

## Prerequisites
1. Ensure the system is properly set up with virtual environment activated
2. Have test files ready in `docs/Testing/Short/`
3. Verify the server is running on port 8000

## Test Procedure

### 1. Start the Server
```bash
source venv/bin/activate
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
```

### 2. Prepare Test Files
The test uses two files from `docs/Testing/Short/`:
- `Specifications Short.pdf` - PDF specification document
- `Instructions short.txt` - Text instructions to paste

### 3. Run the Test Script
```bash
python tests/test_2channel_amplifier.py
```

### 3b. Optional: Simulate Step 3 From Saved AI Outputs (No API Calls)
Use this to replay Step 3 deterministically and validate the post‑AI pipeline only.

```bash
# Rebuild lowlevel from saved AI responses for a specific run
python tests/simulate_step3_from_ai_output.py --run-id <run-id>

# Then analyze lowlevel circuits (forensic gates)
python tests/analyze_lowlevel_circuits.py output/<run-id>/lowlevel
```

Expected: Zero critical issues. Modules may have non-critical warnings depending on complexity. Target: all eight forensic checks pass.

### 4. Monitor Each Step

#### Step 1: Information Gathering
**Expected Output:**
- Should extract all specifications WITHOUT asking for clarification
- Should identify: 2 channels, 50kHz and 1.5MHz transducers
- Should extract power requirements: 360Vpp/200W and 280Vpp/158W

**Verification:**
```bash
# Check Step 1 completed without clarification
grep "needs_clarification.*false" logs/workflow_*.log
```

#### Step 2: High-Level Design
**Expected Output:**
- ONLY PNG and DOT files in `highlevel/` folder
- NO JSON files in highlevel folder
- System diagram showing actual components (NOT generic "24V DC" or "RF Output")
- Should generate 4-8 modules for complex circuits

**Verification:**
```bash
# Check highlevel folder - should ONLY have PNG and DOT files
ls output/*/highlevel/
# Should see: system_overview.png, system_overview.dot
# Should NOT see any .json files
```

#### Step 3: Low-Level Circuit Design
**Expected Output:**
- 4-8 circuit JSON files in `lowlevel/` folder (depends on complexity)
- Each circuit MUST be 100% complete with:
  - ZERO floating components (all pins connected or marked NC)
  - ZERO invalid pin references
  - ZERO single-ended nets
  - Proper connections for ALL components
  - Validation status: "PERFECT"
  - Power rail naming accepted in ANY modern form (e.g., VCC_5V, V3P3, VDD_CORE, VIN_PROTECTED)

**Verification (Use Official Test Script):**
```bash
# Run comprehensive analysis
python tests/analyze_lowlevel_circuits.py output/[UNIQUE_ID]/lowlevel

# Expected output:
# ✅ ALL CIRCUITS ARE 100% PERFECT!
# Ready for production and PCB manufacturing
```

**Checks Performed:**
1. Floating component check (CRITICAL) - All pins must be connected
2. Single-ended net check - All nets have multiple connection points
3. Invalid pin reference check - All pins exist in component definitions
4. Phantom component check - All referenced components exist
5. IC power connection check - All ICs have VCC/GND
6. Duplicate connection check - No duplicate connections
7. Net consistency check - Nets properly formed
8. Circuit supervisor status - Must be "PERFECT"

Note: As of 2025-10-26, the supervisor’s power/ground heuristics are generic and robust; rails like `VCC_5V`, `V3P3`, `VDD_CORE`, `VIN_PROTECTED` are treated correctly as power/ground where appropriate.

**Example Results:**
```
Circuit: circuit_power_supply_module
  Components: 36
  Connections: 15
  Completeness: 100.0%
  Status: ✅ PERFECT
```

### 5. Critical Quality Checks

#### Check 1: No JSON in Highlevel
```bash
# This should return nothing
ls output/*/highlevel/*.json 2>/dev/null
```

#### Check 2: Proper Module Names
Circuits should have meaningful names based on their function for example:
- `circuit_power_supply_unit.json`
- `circuit_control_and_signal_generation.json`
- `circuit_channel_1_driver_50khz.json`
- `circuit_channel_2_driver_1.5mhz.json`

#### Check 3: Component Quality
```bash
# Check for proper component specs
grep -h "suggestedPart" output/*/lowlevel/*.json | sort | uniq
```

### 6. Common Issues and Solutions

#### Issue: Step 2 generates JSON files in highlevel
**Solution:** Check `workflow/step_2_high_level.py` lines 907-928 are removed

#### Issue: Default diagram shows "24V DC" and "RF Output"
**Solution:** Ensure Step 2 generates context-aware diagrams based on actual circuit type

#### Issue: Step 3 timeout
**Solution:** Verify 5-minute timeout is set in `ai_agents/agent_manager.py`:
```python
timeout = 300.0 if 'step_3' in step_name.lower() else 120.0
```

#### Issue: Module extraction failure
**Solution:** Check `workflow/circuit_workflow.py` properly extracts modules from Step 2:
```python
modules = high_level_design.get('modules', [])
circuit_name = high_level_design.get('designParameters', {}).get('devicePurpose', 'Circuit')
```

### 7. Expected Timeline
- Step 1: ~8 seconds
- Step 2: ~60 seconds
- Step 3: ~4-5 minutes (with 4 modules)
- Step 4: ~2-3 minutes (if Mouser API is working)
  - Real-time progress for Step 4 is now visible in the UI (WebSocket `step_progress`) with incremental ETA updates.
- Step 5-6: ~30 seconds

### 8. Success Criteria
✅ Step 1 completes without clarification
✅ Step 2 generates ONLY PNG and DOT files
✅ Step 2 diagram shows actual circuit components
✅ Step 3 generates 4-8 modules for complex circuits
✅ ALL circuits have validation status "PERFECT"
✅ ALL circuits have ZERO floating components
✅ ALL circuits have ZERO invalid pin references
✅ ALL circuits have proper connections
✅ Circuit files are properly named
✅ No hardcoded values in diagrams
✅ 100% completeness score for all circuits

### 9. Step 5: Quality Assurance (New)
- Runs deep forensic validators on all outputs:
  - Lowlevel: analyze_lowlevel_circuits.py (8 checks)
  - KiCad: validate_kicad_deep_forensic.py (preflight + validate_kicad_forensic.py → ERC/DRC and format)
  - Eagle: validate_eagle_deep_forensic.py (preflight + validate_eagle_comprehensive.py → geometry/structure)
  - EasyEDA Pro: validate_easyeda_pro_deep_forensic.py (preflight + EasyEDA forensic)
  - Schematics (PNG): validate_schematics_deep_forensic.py (coverage + file size)
  - Schematics Description (Text): validate_schematics_desc_deep_forensic.py (per‑circuit presence + content heuristics)
- Produces two reports in `output/[RUN]/qa/`:
  - `user_qa_report.html` — clean, professional summary (included in ZIP package)
  - `internal_qa_report.json` + `internal_qa_report.html` — thorough forensic details (internal only, not packaged)
- UI shows progress and a final PASS/FAIL badge.

Quick commands (targeted):
```bash
# After running a converter, validate deeply:
python tests/validate_kicad_deep_forensic.py
python tests/validate_eagle_deep_forensic.py
python tests/validate_easyeda_pro_deep_forensic.py
python tests/validate_schematics_deep_forensic.py
python tests/validate_schematics_desc_deep_forensic.py
```

### 10. Step 6: Packaging (New)
- Creates a ZIP with README and manifest (project.json):
  - Path: `output/[RUN]_circuit_design.zip`
  - Includes relevant subfolders and excludes sensitive/diagnostic content:
    - Excludes: `lowlevel/`, `kicad/ERC/`, `kicad/DRC/`, `eagle/ERC/`, `eagle/DRC/`, and internal QA reports.
    - Includes: `qa/user_qa_report.html` for end‑user QA summary.
- Download via API:
  - `GET /api/download/{project_id}` → returns the ZIP file

## Automated Test Commands

### Complete Workflow Test
```bash
# Start server and run full test
python tests/test_2channel_amplifier.py
```

### Circuit Validation Test
```bash
# Validate all lowlevel circuits (CRITICAL)
python tests/analyze_lowlevel_circuits.py output/[UNIQUE_ID]/lowlevel

# Expected: "✅ ALL CIRCUITS ARE 100% PERFECT!"
```

### Step 3 Simulation Test
```bash
# Test Step 3 workflow with AI outputs
python tests/test_step3_real_simulation.py

# This test:
# 1. Loads AI module outputs from logs
# 2. Runs through circuit supervisor
# 3. Validates all circuits
# 4. Reports any issues
```

## Important Test Files

### 1. analyze_lowlevel_circuits.py
Location: `tests/analyze_lowlevel_circuits.py`

**Critical validation script** - Must pass 100% for production.

Performs 8 comprehensive checks:
- Floating component detection (all pins)
- Single-ended net detection
- Invalid pin reference validation
- Phantom component detection
- IC power connection verification
- Duplicate connection detection
- Net consistency validation
- Circuit supervisor status check

Circuit Supervisor now also checks for shorted passives:
- Shorted passive detection (2-terminal components with both pins on same net)
- This is critical for SPICE simulation - components like `R1 0 0 10k` carry zero current

**To manually check for shorted passives:**
```python
from workflow.circuit_supervisor import CircuitSupervisor
import json

with open('output/<run>/lowlevel/circuit_xxx.json') as f:
    data = json.load(f)
circuit = data.get('circuit', data)

supervisor = CircuitSupervisor()
issues = supervisor._check_shorted_passives(circuit)
print(f"Shorted passives: {len(issues)}")  # Should be 0
```

### 2. test_step3_real_simulation.py
Location: `tests/test_step3_real_simulation.py`

Simulates exact production workflow:
- Loads AI module outputs from logs
- Runs circuit text parser
- Applies circuit supervisor
- Validates all outputs
- Reports issues and fixes

### 3. test_step3_simulation.py
Location: `tests/test_step3_simulation.py`

End-to-end Step 3 test with live AI calls.

## Historical Test Results

> **Note**: The results below are from October 2025 testing with a single 6-module test case (230 components). The system has since been tested with more complex designs (7-9 modules, 350-465 components). Quality varies with circuit complexity and AI non-determinism. See `QUALITY_BASELINE.md` for current metrics.

### KiCad Converter Forensic Validation (October 2025)

**Validation Type**: Forensic-level production quality check
**Validation Cycles**: 2 (iterative fix-and-validate loop)

**Final Results**: PERFECT - 100% QUALITY SCORE

**Forensic Validation Metrics:**
- Quality Score: 100%
- Total Errors: 0
- Total Warnings: 0
- Files Validated: 18 (6 projects x 3 file types)

**Circuit Statistics:**
- Projects: 6
- Components: 230
- Nets: 741
- Schematic Wires: 463
- PCB Traces: 463
- Footprints: 230

**Production Readiness Assessment:**
- Files open cleanly in KiCad 8.0+ and 9.0+
- 100% ERC/DRC compliance
- All required metadata present
- Proper S-expression format
- Complete connectivity information

**Test Script Used**: `tests/validate_kicad_forensic.py`

---

### Full Pipeline Test (October 2025)

**Duration**: ~17 minutes
**Results**: ALL 6 CIRCUITS 100% PERFECT

| Circuit | Status | Notes |
|---------|--------|-------|
| circuit_power_supply_module | PERFECT | LM317HV pinout validated |
| circuit_main_controller_module | PERFECT | All connections validated |
| circuit_channel_1_module | PERFECT | All connections validated |
| circuit_channel_2_module | PERFECT | All connections validated |
| circuit_front_panel_interface | PERFECT | All connections validated |
| circuit_backplane_interconnect | PERFECT | All connections validated |

**Component Statistics:**
- Total components: 230
- Unique parts: 73

**Converter Results:**
- 50+ output files generated (BOM, Eagle, KiCad, EasyEDA Pro, Schematics)
- 0 Critical, 0 Issues, 0 Warnings
- All 8 forensic checks passed

## Notes
- Quality depends on circuit complexity: simple designs (1-3 modules) achieve higher perfection rates than complex multi-module designs (7+ modules)
- This is a UNIVERSAL circuit design system (not just amplifiers)
- Module consolidation: Simple 1-3, Medium 2-5, Complex 4-8 modules
- No tolerance for floating components or invalid pins in production
- All AI-generated circuits require professional engineering review before fabrication

---

## Modern Testing Framework (October 2025 Update)

### Pytest Integration

As of October 27, 2025, the test suite has been modernized with pytest framework:

**New Testing Commands:**
```bash
# Run all converter tests with pytest
pytest -m "converter" -v

# Run quick smoke tests (skip slow forensic tests)
pytest -m "not deep" -v

# Run specific converter test
pytest tests/test_kicad_converter.py -v

# Backwards compatible - old script style still works
python tests/test_kicad_converter.py
```

**Test Categories (Pytest Markers):**
- `@pytest.mark.converter` - Converter tests (6 tests, ~2 min each)
- `@pytest.mark.validator` - Validation tests
- `@pytest.mark.simulation` - Simulation tests (quick, <30s)
- `@pytest.mark.deep` - Deep forensic tests (slow)

**Benefits:**
- Better organization with fixtures
- Clear pass/fail reporting
- Selective test execution with markers
- Backwards compatible (scripts still work)

### Verification Folder Structure

All validation artifacts are now centralized in `verification/` folder:

```
output/[UNIQUE_ID]/
├── lowlevel/              ← Circuit designs
├── kicad/                 ← KiCad outputs (CLEAN)
├── eagle/                 ← Eagle outputs (CLEAN)
├── easyeda_pro/           ← EasyEDA Pro outputs (CLEAN)
├── bom/                   ← BOM files (CLEAN)
├── schematics/            ← PNG diagrams (CLEAN)
├── schematics_text/       ← Text descriptions (CLEAN)
├── verification/          ← **ALL VALIDATION ARTIFACTS** (NEW)
│   ├── kicad/
│   │   ├── erc/          ← ERC reports
│   │   ├── drc/          ← DRC reports
│   │   └── forensic/     ← Forensic analysis
│   ├── eagle/
│   │   ├── erc/
│   │   ├── drc/
│   │   └── forensic/
│   ├── lowlevel/
│   │   └── analysis/     ← analyze_lowlevel_circuits.py output
│   ├── step5_qa/         ← Step 5 QA/QC reports
│   └── logs/             ← Test execution logs
└── qa/                    ← User-facing QA reports

**Purpose:**
- Clean separation: outputs vs validation
- Not packaged in ZIP (internal only)
- Used by Step 5 QA/QC
- Historical validation records for debugging
```

**Benefits:**
- ✅ Clean separation of concerns (outputs vs validation)
- ✅ Easy to find validation results
- ✅ Perfect for Step 5 QA/QC integration
- ✅ Not shown to end users
- ✅ Centralized validation artifacts

### Test Suite Organization

**26 Production Test Scripts:**

**1. Core Validators (8)** - MANDATORY
- `analyze_lowlevel_circuits.py` ⭐ MOST CRITICAL
- `validate_kicad_forensic.py`
- `validate_eagle_comprehensive.py`
- `validate_easyeda_pro_forensic.py`
- `validate_eagle_files.py`
- `validate_ratsnest.py`
- `validate_lowlevel_circuits.py`
- `run_all_converter_tests.py`

Additionally (PNG/Text schematics validators):
- `validate_schematics_deep_forensic.py` (schematics PNG coverage + structural parity)
- `validate_schematics_desc_deep_forensic.py` (text wiring coverage + plausibility)

**2. Converter Tests (6)** - Pytest format
- `test_kicad_converter.py`
- `test_eagle_converter.py`
- `test_easyeda_pro_converter.py`
- `test_bom_converter.py`
- `test_schematics_converter.py`
- `test_schematics_text_converter.py`

**3. Simulation Utilities (6)** - NEW (Oct 27, 2025)
- `simulate_kicad_conversion.py`
- `simulate_eagle_conversion.py`
- `simulate_easyeda_pro_conversion.py`
- `simulate_schematics_conversion.py`
- `simulate_schematics_desc_conversion.py`
- `simulate_step3_from_ai_output.py`

**4. Deep Validation Wrappers (5)** - NEW (Oct 27, 2025)
- `validate_kicad_deep_forensic.py`
- `validate_eagle_deep_forensic.py`
- `validate_easyeda_pro_deep_forensic.py`
- `validate_schematics_deep_forensic.py`
- `validate_schematics_desc_deep_forensic.py`

**5. Step Simulation Tests (2)**
- `test_step2_simulation.py`
- `test_step3_simulation.py`

### Archived Tests

**14 legacy scripts moved to `tests/archive/` (Oct 2025 cleanup):**
- `step3_redundant/` (4 files)
- `manual_tools/` (3 files)
- `legacy_validators/` (4 files)
- `old_integration/` (3 files)

See `tests/archive/README.md` for details.

### Quick Testing Workflows

**Development Testing:**
```bash
# Quick smoke test (2 minutes)
pytest -m "not deep" -v

# Simulate + validate pattern (recommended)
python tests/simulate_kicad_conversion.py
python tests/validate_kicad_deep_forensic.py
```

**Pre-Commit:**
```bash
# Run all converter tests
python tests/run_all_converter_tests.py
# OR
pytest -m "converter" -v
```

**Pre-Release:**
```bash
# Complete validation suite
python tests/run_all_converter_tests.py
pytest -v --tb=long
python tests/analyze_lowlevel_circuits.py output/[latest]/lowlevel
python tests/validate_kicad_deep_forensic.py
python tests/validate_eagle_deep_forensic.py
python tests/validate_easyeda_pro_deep_forensic.py
```

### Documentation

**Test Documentation:**
- `tests/README.md` - Comprehensive test documentation
- `tests/TESTING_STRATEGY.md` - Testing philosophy and best practices
- `tests/archive/README.md` - Archived tests documentation
- `pytest.ini` - Pytest configuration (project root)
- `tests/conftest.py` - Shared pytest fixtures

- **Unified Guide:**
- `docs/TESTING_GUIDE.md` - This document (quick + complete)
- `docs/KICAD_CONVERTER.md` - KiCad-specific testing
- `docs/EAGLE_CONVERTER.md` - Eagle-specific testing

---

**Last Updated**: February 2026
**Test Suite Version**: 2.0 (Pytest Modernization)
