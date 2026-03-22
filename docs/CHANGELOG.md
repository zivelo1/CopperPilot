# CopperPilot Changelog

All notable changes to CopperPilot are documented here.

---

## March 2026 — KiCad Schematic Connectivity Overhaul

### KiCad Converter
- **Label-per-pin connectivity**: Replaced chain wire topology (which caused cross-net shorts) with individual global labels at every pin's stub endpoint. Each pin gets its own label — KiCad connects electrically by name. Eliminates all wire-crossing DRC violations in schematics.
- **Multi-unit symbol support**: Dual op-amps and other multi-unit symbols (e.g., LM2904, OPA2134) now generate ALL units (A, B, and power) instead of only unit A. Prevents `missing_unit` and `pin_not_connected` ERC errors.
- **Power pin mapping from circuit JSON**: Power unit pin-to-net mapping now uses the actual `pinNetMapping` from the circuit JSON as primary source, with guessing as fallback only. Fixes `power_pin_not_driven` errors when circuit uses non-standard power net names (e.g., `V_NEG_15` instead of `GND`).
- **Duplicate unit prevention**: Fixed power unit being generated twice (once by the all-units loop, once by the legacy power unit code).

### New: Schematic Label Post-Processor (`scripts/kicad/fix_schematic_labels.py`)
- Standalone post-processor that fixes global label positions using actual KiCad symbol geometry.
- Parses `lib_symbols` section with `sexpdata` to extract true pin offsets per unit.
- Calculates pin positions from symbol instance placements (position + rotation + unit).
- Generates stub wires pointing OUTWARD from symbol body (180° flip from pin angle).
- Verifies results with `kicad-cli` ERC when available.
- Generic — works for any circuit topology, any component types.

### KiCad 10 Compatibility
- Verified output opens in KiCad 10.0.0 (auto-converts from KiCad 9 format).
- `kicad-cli` ERC/DRC validation tested against KiCad 10.

---

## February 2026 — Integration Stitching, Auxiliary Passives & Validation

### Supervisor & Config
- **Power pin/rail detection**: Migrated power pin names to centralized config (30+ entries: VPOS, VNEG, VS+, VS-, VCCA, PVDD, COMM, etc.). Added `RAIL_`, `SUPPLY_`, `[+-]?\d+V\d*_` patterns to power rail detection.
- **Config pin exemption**: New `CONFIG_PIN_KEYWORDS` (ADDR, MODE, SEL, CFG, BOOT, STRAP) — pins tied to VCC/GND skip mismatch checks.

### Integration Agent
- **Same-name net auto-merge**: Nets appearing in 2+ modules with identical names are automatically shared (not prefixed). Fixes cross-module `SW`, `SYS_PG`, `VOUT_5V` stitching.
- **External input classification**: System-boundary inputs (VIN_RAW, MAINS, BATT) excluded from connection ratio via `EXTERNAL_INPUT_NET_PATTERNS`.
- **Self-contained signal recognition**: Signals with 2+ internal connections not penalized as unmatched.
- **Physical port audit**: Validates every `SYS_*` or global net connects to a physical port (connector/header/test_point).
- **Enhanced hardware prefix stripping**: 17 MCU-specific prefix patterns (added HRTIM, LPTIM, DMA, SAI, SDMMC).

### Prompt Enforcement
- **"No Naked Auxiliaries" rule**: Added to ALL design prompts — 7 auxiliary pin categories (filter/compensation, offset, bias, soft-start, bootstrap, average/RMS, buffer) with required passive types. ERC hints for IC-prefixed single-ended nets.

### SPICE
- **Subcircuit name sanitization**: `spice_safe_name()` applied once before wrapper creation, fixing `.subckt`/`X` instance name mismatches (e.g., AMS1117-3.3 → AMS1117_3.3).

### Rating Validator
- **Per-net voltage domain**: xVy notation support (3V3 → 3.3V, 1V8 → 1.8V) for accurate per-rail voltage checking.

---

## February 2026 — Quality Gate & Genericity Hardening

### Validation
- **Severity-aware pass/fail**: `all_passed` checks `critical_issues == 0` (not `total_issues == 0`). Circuits with only warnings correctly report PASSED.

### Postprocessor
- **Design artifact detection**: Removes AI thinking leftovers (Q1_REPLACED, R3_OLD, DNP values) via config-driven suffix/keyword lists.

### Pattern Coverage
- **40+ new interface/exempt patterns**: Voltage return paths, power good signals, transistor nodes, measurement/instrumentation, clock/timing, interrupts, enable/standby, pin-reference nets, hardware-prefixed peripherals, 14 additional module abbreviation prefixes.

---

## February 2026 — Pipeline Integrity

- **Design.json quality gate timing**: Fixer now runs BEFORE `create_design_summary()` — `circuitFixerPassed` is no longer stale.
- **Step3 success propagation**: `step3_success` + `qualityGates` breakdown now written to design.json.
- **Attribute access fix**: Dict `.get()` access in single-agent return value (was using attribute access on dict).

---

## February 2026 — Genericity & Forensic Fixes

### Validation
- **LAW 4 expanded**: Stage 2 prompt covers all 2-pin passive types (thermistors, fuses, ferrite beads, varistors, crystals, LEDs).
- **Deterministic LAW 4 auto-fix**: `_enforce_law4_different_nets()` in postprocessor moves shorted passive pins to `{net}_B`.

### Integration & SPICE
- **Semantic matching**: Hardware prefix stripping + functional keyword overlap matching for integration signals.
- **Unified SPICE sanitization**: `spice_safe_name()` in shared `spice_utils.py` — eliminates Unicode mismatch.
- **Potentiometer SPICE model**: Voltage divider at 50% wiper position.

### Structural Genericity
- **28 new interface patterns**: Power stage, adjustment, current sensing, protection, motor, audio.
- **Isolation domain awareness**: Component `specs.isolation_domain` metadata check before pattern matching.
- **Config-driven structural rules**: All hardcoded ref prefix checks replaced with `CONNECTOR_REF_PREFIXES`, `TESTPOINT_REF_PREFIXES`, `GENERIC_MODULE_PREFIX_PATTERNS`.

---

## February 2026 — Showcase Hardening

- **Single-agent fixer gate fix**: `.get()` on `ValidationResult` dataclass caused `step3_success` to be always False. Now uses `_run_circuit_fixer()` helper (returns dict).
- **Fallback circuit cleanup**: Pins mapped to exactly one net each (VCC/GND only), removing false net conflicts.
- **Dead code removal**: 3 unused layout engine files removed, `layout_engine_fixed.py` renamed to `layout_engine.py`.
- **Defensive coding**: `getattr(component, 'specs', None) or {}` prevents `AttributeError`.

---

## February 2026 — SPICE Value Parsing & Power Source Detection

### SPICE Model Library
- **Type descriptor stripping**: `SPICE_VALUE_TYPE_DESCRIPTORS` (20 words: NTC, ceramic, electrolytic, x5r, etc.) stripped from component values before parsing.
- **Part number false positive fix**: Removed overly broad `^\d+[A-Za-z]+` regex that matched SI-prefixed values like "10k".
- **Model value priority**: `_format_component_statement()` uses `model.default_params['value']` when available.

### SPICE Netlist Generator
- **Power source detection**: 6 new patterns (VOUT_xV, VIN_xV, generic `*_xV$`) + secondary detection pass bridging `POWER_RAIL_PATTERNS` to voltage extraction.

### AI Agent Manager
- **Prefill removal**: `assistant_prefill` code path removed — Claude Opus 4.6 does not support assistant message prefill.

---

## February 2026 — Stage 2 & Step 3 Data Flow

- **Stage 2 token limit**: `max_tokens` increased 8000 → 16000 to prevent JSON truncation.
- **False PERFECT fix**: Replaced unconditional success log with actual validation status check.
- **Data flow**: `operating_voltage` and `isolation_domain` now flow from Step 2 into Step 3 module context.
- **JSON enforcement**: Strengthened JSON-only instructions in Stage 1 and Stage 2 prompts.

---

## February 2026 — Comprehensive Code Audit & Hardening

Full-codebase audit across 7 pipeline files.

### Safety & Crash Fixes
- **Fail-closed default**: `use_multi_agent` changed from `True` to `False`.
- **Empty-string guards**: 10+ `.get()` gotcha locations fixed with `or` chaining across model_library, circuit_fixer, circuit_supervisor, integration_agent.
- **KeyError prevention**: Direct key access replaced with `.get()` throughout.

### Config Centralization
- **5 new config type sets**: `TWO_PIN_PASSIVE_TYPES` (12), `TWO_PIN_PASSIVE_PREFIXES` (6), `VOLTAGE_RATED_TYPES` (21), `FLOATING_INPUT_KEYWORDS` (8), `DESIGN_SUPERVISOR_POWER_SIGNAL_PATTERNS` (12).

### Dead Code Removal
- Deleted `IssueClassifier` class (47 lines, never instantiated).
- Deleted `validate_integration()` function (60 lines, never called).
- Removed unused imports.

---

## February 2026 — Forensic Validation Fixes

### Config
- 6 power rail patterns + 5 interface patterns added.
- SPICE patterns for `POWER_xV`, `*_VCC$`, `*_VDD$` variants.
- `SPICE_SUBCIRCUIT_OUTPUT_PIN_NAMES` frozenset (14 pin names) prevents voltage source loops.

### Circuit Supervisor
- **Power detection symmetry**: Pin-name power check now symmetric with ground check (21 entries).
- **Reference shunt exemption**: Added `and not is_ref_shunt` to ground check.

### Schematic Pipeline
- **Python None crash fix**: `specs=comp_data.get('specs') or {}` prevents crash when JSON has `"specs": null`.

---

## February 2026 — Architecture & Professional Schematics

- **Step 2 typed interfaces**: Inputs/outputs use objects with `signal_type`, `voltage`, `description`.
- **Isolation domain enforcement**: Mandatory `isolation_domain` field prevents accidental cross-domain net merging.
- **Symbol engine**: `SymbolLibrary` maps component types to IEEE/IEC symbol primitives.
- **Functional clustering**: Layout engine uses isolation domain as primary clustering weight.
- **Tiered documentation**: Tier 1 (Power), Tier 2 (Primary Signal), Tier 3 (Auxiliary Logic).

---

## February 2026 — Single Source of Truth

- **"Two Brains" elimination**: Deleted `CircuitAnalysisEngine` (50+ hardcoded patterns), delegated to `CircuitSupervisor.run_erc_check()`. Refactored `_is_interface_signal()` from 60+ hardcoded patterns to config-driven checks.
- **30+ new interface patterns**: DISPLAY, bare FAULT/ENABLE/RESET/PWM/CTRL, VREF, power domain signals, UI signals.
- **Duplicate subcircuit fix**: `_required_subcircuits` changed from `Set[str]` to `Dict[str, str]` (name-based dedup).
- **Test script alignment**: Test scripts use same config patterns as production code.

---

## February 2026 — SPICE Pin Ordering & Power Source Fixes

- **Pin reordering**: `_reorder_nodes_to_spice_order()` fixes MOSFET D/G swap, BJT C/B/E order, Diode A/K order. Falls back to positional ordering.
- **Pin name aliases**: `SPICE_PIN_NAME_ALIASES` maps 30+ AI-generated variants to canonical names.
- **Power source suffix patterns**: Nets like `+12V_DIGITAL`, `+180V_DC` now match. Added `HV_`/`LV_` prefix patterns.

---

## February 2026 — Forensic Analysis Run 5 (18 fixes)

- **Active device classification**: `NON_ACTIVE_COMPONENT_TYPES` (36 types) eliminates false-positive power errors for connectors, switches, terminals.
- **Fuzzy signal matching**: Integration agent fuzzy fallback + ERROR escalation for unmatched signals.
- **Fail-closed quality gates**: `fixer_gate_passed` and `integration_gate_passed` default `False`.
- **SPICE behavioral models**: `BEHAVIORAL_MODEL_PIN_MAP` (13 ICs) with pin-count-aware wrappers.
- **Interface contract injection**: `_build_interface_contract_text()` injected into all AI prompt paths.
- **Feedback divider check**: Vout = Vref * (1 + Rtop/Rbottom), flags deviations > 2%.
- **Connector SPICE model**: Independent pin-to-internal-node passthrough (no cross-shorting).
- **Ferrite bead classification**: `SpiceType.RESISTOR` using impedance value.
- **Electromechanical taxonomy**: switch, relay, buzzer, motor, solenoid, speaker, piezo.

---

## February 2026 — Config Centralization & Enhancement (18 fixes)

- All patterns centralized in `server/config.py` with zero duplication across consumers.
- 11 new config entries: `POWER_RAIL_PATTERNS`, `OPTOCOUPLER_PART_PATTERNS`, `SUPERVISOR_GPIO_PATTERNS`, etc.
- SPICE import path fix (subprocess `sys.path` + `cwd`).
- KiCad profiler method fix (`print_report()` → `report()`).
- Eagle symbol library expansion (5 new types + dynamic transformer).
- Rating DB consolidation: 177 entries in external `data/component_ratings.json`.
- Eagle converter: diagnostic `print()` → `logger.warning()`, IC odd pin count fix.

---

## February 2026 — Integration Agent & Cross-Module Connectivity (21 fixes)

- **Signal stitching**: Integration Agent results written back to per-module circuit files.
- **Prefix map**: Pin references correctly prefixed for cross-module component references.
- **Phantom prevention**: `_remove_phantom_references()` validates all pin refs against component list.
- **Dangling detection**: `_warn_dangling_internal_nets()` detects single-connection internal nets.
- **Supervisor false positive reduction**: GPIO/AGND/PGND/dual-supply filtering.
- **Dynamic power/ground detection**: `_detect_power_rail()` and `_detect_ground_rail()` scan existing nets.
- **Severity classification**: All ERC issues carry CRITICAL/HIGH/MEDIUM/LOW severity.

---

## February 2026 — Pipeline Overhaul

- Integration agent signal matching overhaul.
- Mega-module elimination.
- Circuit fixer hard gate (configurable critical issue threshold).
- BOM extraction pipeline fix (disk-based circuit loading).
- SPICE ground pattern fix (exact/prefix/suffix matching).
- Per-run step logging fix (logger bridging).
- Honest quality metrics (cross-reference fixer/rating reports).
- Prompt engineering (operating_voltage, LAW 8, Rules 6-7).
- Rating validator voltage domain support (per-module).
- Power connection post-processor.

---

## February 2026 — System Fixes

- **Write-as-you-go architecture**: Circuits written immediately to disk, memory freed.
- **LAW 4 enforcement**: `shorted_passives` added to fix order.
- **Interface signal matching**: Enhanced to search component pin names as fallback.
- **EasyEDA Pro crash fix**: Undefined `context` variable reference removed.
- **Eagle exception handling**: Typed error reporting replaces broad `except Exception`.
- **BOM grouping**: Package included in group key (`{type}_{value}_{package}`).
- **Floating IC input detection**: Critical issues flagged.

---

## January 2026 — Multi-Agent Architecture

Hierarchical multi-agent system for complex circuit design:
- `DesignSupervisor` → `ModuleAgent` (per module) → `ComponentAgent` + `ConnectionAgent` + `ValidationAgent`
- `IntegrationAgent` for cross-module integration
- Context isolation: each agent handles 20-50 components (vs 200+ previously)
- Automatic activation for 3+ module designs

---

## December 2025 — SPICE/LTSpice Converter

New SPICE netlist (`.cir`) and LTSpice schematic (`.asc`) generation:
- Compatible with ngspice, LTSpice, HSPICE, PSpice
- Simulation validator framework for automated requirement checking
- Value sanitization for SPICE-incompatible formatting

---

## December 2025 — Routing Architecture Change

Freerouting (Java autorouter) replaced with Manhattan router (pure Python):
- No Java dependency required
- Manhattan router bugs are fixable; Freerouting reliability was not
- Pure Python grid-based collision-free routing with MST topology

---

## December 2025 — KiCad Routing Overhaul (6 phases)

Complete routing rewrite:
- S-expression parser replaces regex for safe PCB modification
- Collision detection blocks all obstacles per-layer
- Snap-to-pad with exact coordinates and stub segments
- Via placement with pad clearance
- Solder mask margin inflation
- AI fixer recovery with `remove_all_routing()` and re-route
- Dynamic routing with finer grid fallback (0.25mm, 0.1mm)

---

## November 2025 — 7-Step Workflow

- Updated from 6 to 7 steps (added Format Conversion as separate step)
- PDF content persistence across clarification rounds
- Per-AI-call cost tracking and display
- ETA updates after each module completes

---

## November 2025 — DFM Validation System

Design for Manufacturability integrated into all converters:
- 3 fabricator databases: JLCPCB, PCBWay, OSH Park
- 8 comprehensive checks: trace width/spacing, drill sizes, vias, clearances, board size, layers, silkscreen
- Auto-fix engine for 70%+ violations
- Professional HTML reports

---

## November 2025 — Footprint & Component Improvements

- Generic footprint mapper (`scripts/kicad/footprint_mapper.py`) with 50+ mappings and 4-level fallback
- Footprint library integration: exact pad data from KiCad `.kicad_mod` files
- Intelligent multi-signal component type detection (value keywords, ref designators, pin count, type field)
- Modular validator architecture for Eagle (standalone ERC/DRC/DFM validators)

---

## October 2025 — Initial Production Release

- Eagle converter v15.0: 100% pass rate with MST wire routing
- KiCad converter v10.0: net-aware routing with 100% success rate
- EasyEDA Pro converter v2.1: complete array-based format support
- Dual-supplier BOM system (Mouser + Digikey)
- Circuit validation: 8 comprehensive checks, fail-closed quality gates
- Generic power rail detection for modern naming conventions
