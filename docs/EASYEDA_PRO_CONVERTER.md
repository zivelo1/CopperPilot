# EasyEDA Professional Converter [EXPERIMENTAL]

**Target Format**: EasyEDA Pro (.epro)
**Status**: EXPERIMENTAL — Self-Healing Enabled, Pure Python Routing. Dense circuits (40+ components) may experience routing congestion. Use KiCad converter for production-grade output.

> **Known Limitation**: The Manhattan Router cannot reliably route circuits with 40+ components and 50+ nets. Dense boards experience routing congestion that the self-healing loop cannot resolve. Works well for simpler circuits (<30 components). See Known Limitations below.

## Crash Fix (February 2026)

**Problem**: Undefined `context` variable reference at line 911 caused converter to crash during batch processing.

**Root Cause**:
```python
# Line 911 (BEFORE):
self._write_verification_reports(circuit_name, context)  # context undefined here!
```

The `context` variable was only defined inside the processing loop but was being referenced outside of it.

**Solution**: Removed the orphaned verification report call - reports are now written inside `_process_single_circuit` where the context is properly defined.

**Impact**: EasyEDA Pro converter no longer crashes on batch processing.

---

## Overview

The EasyEDA Professional Converter transforms lowlevel circuit JSON into production-ready `.epro` project files. It features a robust, self-healing architecture that mirrors the proven KiCad converter design.

### Routing Changes (December 2025)

*   **Freerouting Removed**: Uses pure Python Manhattan router (no Java dependency)
*   **Output Guarantee**: Converter always saves output files even when routing fails
*   **Parity Guaranteed**: N lowlevel circuits produce N .epro output files

### Key Capabilities

*   **Self-Healing Loop**: Automatically detects routing failures (timeouts, zero segments) and retries with optimized strategies.
*   **Format Parity**: Generates valid PCB 1.8 / SCH 1.1 array-based formats.
*   **Net-Aware Routing**: Assigns tracks to nets to prevent short circuits.
*   **Modular Footprints**: Generates adaptive footprints for 1-100+ pins.
*   **Fail-Closed Validation**: Blocks release of incomplete or unrouted boards.

## Architecture

### The "KiCad Concept" (Self-Healing)

The converter implements a feedback loop to handle complex circuits that might fail initial routing attempts:

1.  **Initial Conversion**: Attempts standard conversion with default settings.
2.  **Validation & Diagnosis**:
    *   Checks for missing tracks, DRC errors, or timeouts.
    *   `EasyEdaAiFixer` diagnoses the root cause (e.g., `ROUTING_FAILURE`, `BOARD_TOO_SMALL`).
3.  **Auto-Fix Loop**:
    *   `EasyEdaCodeFixer` applies targeted strategies:
        *   **Relax Constraints**: Reduces trace width/clearance (within limits).
        *   **Expand Board**: Increases board dimensions by 20%.
        *   **Extend Timeout**: Doubles the routing timeout multiplier.
4.  **Retry**: Re-runs the pipeline with the new configuration.

### Pipeline Stages

1.  **Input Processing**: Parses JSON into internal components/nets.
2.  **Library Generation**: Creates symbols and footprints.
3.  **Schematic Builder**: Lays out the schematic.
4.  **PCB Generator**: Places components and generates DSN for routing.
5.  **Pro Assembly**: Converts all data to Pro-specific array format.
6.  **Integration**: Adds JLCPCB part numbers.
7.  **Validation**: Runs ERC, DRC, and DFM checks.

## Routing Integration

The converter uses the shared `scripts/routing/manhattan_router.py` to perform auto-routing.

*   **Adapter**: `scripts/routing/easyeda_adapter.py` converts between EasyEDA structures and the generic `BoardData` format.
*   **Resilience**: Routing failures (e.g., timeouts, unroutable nets) trigger the self-healing loop.

## Validation

The converter strictly enforces quality:

*   **Zero Tolerance**: Any missing footprints, zero-track PCBs, or critical DRC errors result in a FAILED status.
*   **Deep Forensic**: `tests/validate_easyeda_pro_deep_forensic.py` verifies file structure, netlist integrity, and manufacturing constraints.

## Known Limitations

- **Routing congestion on dense circuits**: The Manhattan Router struggles with boards containing 40+ components and 50+ nets. The rip-up-reroute strategy recovers only a fraction of failed nets. For complex multi-module designs, expect partial or failed routing.
- **0% endpoint snapping**: Wire endpoints may not snap to component pads in the PCB layout, requiring manual adjustment.
- **PAD_NET mapping**: Netlist propagation to the PCB layer is incomplete for some component types (MOSFETs, multi-pin ICs).
- **Recommended use**: Simple to moderate circuits (<30 components). For complex designs, prefer KiCad or Eagle converters.

---

## Usage

```bash
python3 scripts/easyeda_converter_pro.py input_folder output_folder
```

**Simulation (Dev/Test):**
```bash
python3 tests/simulate_easyeda_pro_conversion.py
```
(Supports multiprocessing for faster regression testing)