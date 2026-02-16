# SPICE/LTSpice Converter

**Status**: Production Ready
**Target Formats**: SPICE netlist (.cir), LTSpice schematic (.asc)

---

## Overview

The SPICE/LTSpice Converter enables **behavioral simulation** of CopperPilot-generated circuits. While ERC/DRC validates structural correctness, SPICE simulation validates that circuits actually **work as intended** for their application.

### Key Benefits

| Validation Type | What It Checks |
|-----------------|----------------|
| ERC (Electrical Rule Check) | Syntax - valid circuit structure |
| DRC (Design Rule Check) | Manufacturability - PCB constraints |
| **SPICE Simulation** | **Behavior - does it work?** |

**Example**: A circuit can pass ERC/DRC but be an audio amplifier when the user asked for ultrasonic (50kHz). SPICE simulation catches this.

---

## Quick Start

### Basic Usage

```bash
# Activate virtual environment
source venv/bin/activate

# Convert all circuits in a run to SPICE format
python scripts/spice_converter.py output/<run-id>/lowlevel output/<run-id>/spice

# Convert with SPICE netlist only (.cir)
python scripts/spice_converter.py input/ output/ --format spice

# Convert with LTSpice schematic only (.asc)
python scripts/spice_converter.py input/ output/ --format ltspice

# Convert with both formats (default)
python scripts/spice_converter.py input/ output/ --format both
```

### Running Simulations

```bash
# With ngspice (open-source)
ngspice output/spice/power_supply_module.cir

# With LTSpice (GUI)
# Double-click the .asc file or drag to LTSpice window
```

---

## February 2026 Updates

### Import Path Fix

The SPICE converter runs as a subprocess via `converter_runner.py`. Previously, the subprocess did not have the project root on `sys.path`, causing import errors. Fixed by inserting the project root into `sys.path` at startup and passing `cwd=config.BASE_DIR` to `subprocess.run()`. Power rail detection now reads patterns directly from `config.POWER_RAIL_PREFIXES`, `config.POWER_RAIL_EXACT`, and `config.POWER_RAIL_PATTERNS` — eliminating cross-module import issues.

### Pin Ordering & Power Source Fixes

**Pin Reordering:** MOSFET, BJT, DIODE, and JFET component nodes are now reordered from AI-generated pin order to the SPICE-required pin order (D,G,S,B for MOSFET; C,B,E for BJT; A,K for diode; D,G,S for JFET). Uses `SPICE_PIN_NAME_ALIASES` in config to resolve common pin name variants (e.g., "DRAIN"→D, "GATE"→G, "COLLECTOR"→C, "ANODE"→A). Falls back to positional ordering when pin names cannot be resolved.

**Power Source Suffix Patterns:** Power source patterns now match nets with descriptive suffixes like `+12V_DIGITAL`, `+180V_DC`, `+3V3_ANALOG`, `+24V_MOTOR`. Added `HV_`/`LV_` prefix voltage extraction.

### SPICE Model & Syntax Fixes

**B-Source Syntax Fix:** TPS54331 behavioral model used `&` operator and `pulse()` in B-source expressions — both invalid in ngspice. `&` replaced with nested ternary; `pulse()` is only valid in standalone V/I sources, not B-source expressions.

**IC Pin Count Matching:** `BEHAVIORAL_MODEL_PIN_MAP` supports voltage-suffixed IC variants (e.g., `AMS1117-3.3`). Generic fallback strips voltage suffixes for any IC to match behavioral models.

**NTC Thermistor Model:** NTC/PTC thermistors modeled as simple resistors at nominal resistance via `_build_thermistor_model()`. Configured via `NTC_THERMISTOR_TYPES` and `NTC_THERMISTOR_REF_PREFIXES` in config.

**Syntax Pre-Validation:** `_validate_netlist_syntax()` checks for invalid `&` operators in B-source lines, `pulse()` inside B-source expressions, and subcircuit instance vs definition pin count mismatches. Controlled by `SPICE_VALIDATE_SYNTAX` config flag.

**Duplicate Subcircuit Fix:** `_required_subcircuits` uses name-based dedup (`Dict[str, str]`) to prevent duplicate `.subckt` definitions when the same connector type appears multiple times.

### Behavioral Model & Power Source Improvements

**Pin-Count-Aware Behavioral Models:** The model library uses `BEHAVIORAL_MODEL_PIN_MAP` (13 ICs) to match behavioral models based on pin count. When pin counts don't match, `_build_pin_adapted_wrapper()` generates a fuzzy pin-mapped subcircuit wrapper.

**Connector Passthrough:** Connectors generate independent pin-to-internal-node models (100MEG isolation) instead of shorting all pins together.

**Pin Name Deduplication:** `_deduplicate_pin_names()` appends `_<n>` suffixes to duplicate pin names in subcircuit definitions.

**Ferrite Bead Classification:** Ferrite beads classified as `SpiceType.RESISTOR` using impedance value. Configured via `FERRITE_BEAD_TYPES` and `FERRITE_BEAD_REF_PREFIXES` in config.

**Power Source Pattern Ordering:** Two-capture-group patterns (e.g., `3V3` → `3.3`) ordered before single-group patterns. Leading `+`/`-` stripped from net names. Duplicate source tracking prevents double voltage sources.

**Circuit Title Extraction:** Title tries `moduleName`, `circuitName`, `module_name`, then filename stem as fallback.

### Ground Pattern Matching (Phase E)

Ground node assignment uses structured pattern matching from `config.SPICE_GROUND_PATTERNS` (exact/prefix/suffix sets) instead of naive string matching. GND is always assigned to node 0.

### Mandatory Reliability Gate (February 2026)

The SPICE converter now includes a mandatory `ngspice` compile check for every generated `.cir` file:
- **Syntax Check**: Validates that the netlist follows SPICE-2G6/3F5 standards.
- **Sanity Check**: Detects singular matrices, floating nodes, and convergence errors.
- **Fail-Closed**: If a netlist fails this gate, the Step 5 conversion for that module is marked as failed.

### Functional Behavioral Models (February 2026)

"Hollow" resistor-chain stubs have been replaced with functional behavioral models for common complex ICs:
- **AD9833 / AD9851**: Generates a functional sine wave source with frequency control.
- **IR2110 / IR2113**: High/Low side gate driver approximation with dead-time and rail logic.
- **TPS54331**: PWM Buck controller behavioral approximation with soft-start and UVLO.
- **LM358 / TL072**: Improved Op-Amp models with output rail clamping and input bias simulation.

### Value Sanitization

SPICE component values are sanitized to remove units and formatting that SPICE simulators cannot parse (e.g., "10kohm" to "10k", "100uF/50V" to "100u").

---

## Output Files

### Directory Structure

```
output/<run-id>/spice/
├── power_supply_module.cir      # SPICE netlist
├── power_supply_module.asc      # LTSpice schematic
├── main_controller_module.cir
├── main_controller_module.asc
├── channel_1_module_50khz.cir
├── channel_1_module_50khz.asc
└── ...
```

### File Formats

| Extension | Format | Compatible With |
|-----------|--------|-----------------|
| `.cir` | SPICE netlist | ngspice, LTSpice, HSPICE, PSpice |
| `.asc` | LTSpice schematic | LTSpice XVII/24 |

---

## SPICE Netlist Format (.cir)

Example output:

```spice
* Power_Supply_Module

* ======================================================================
* SPICE Netlist: Power_Supply_Module
* Generated by CopperPilot SPICE Converter
* Date: 2025-12-18 10:42:52
* ======================================================================
*
* Components: 52
* Nets: 22
* Connections: 19

* --------------------------------------------------
* Component Statements
* --------------------------------------------------

* Resistors
R1 3 0 1k
R2 13 3 10k

* Capacitors
C1 10 0 470uF
C2 10 0 100nF

* Diodes
D1 11 9 1N5822
DLED1 4 0 LED_GREEN

* Subcircuits (ICs)
XU1 13 0 18 LM7815
XU5 18 0 15 LM7805

* --------------------------------------------------
* Device Models
* --------------------------------------------------
.model 1N5822 D(Is=1.5e-5 Rs=0.03 N=1.25 BV=40 IBV=1m)
.model LED_GREEN D(Is=1e-21 N=1.6 BV=5 IBV=1u)

* Subcircuit Definitions
.subckt LM7815 IN GND OUT
V1 OUT GND DC 15
Rin IN OUT 1
.ends LM7815

* --------------------------------------------------
* Power Sources (Auto-Generated)
* --------------------------------------------------
V_V_5V 15 0 DC 5
V_V_3V3 14 0 DC 3.3
V_V_PLUS_15V 18 0 DC 15

* --------------------------------------------------
* Analysis Commands
* --------------------------------------------------
.op
* .tran 0 10m 0 1u
* .ac dec 100 1 10MEG

.control
run
.endc

.end
```

---

## Component Mapping

The converter automatically maps CopperPilot components to SPICE primitives:

### Passive Components

| CopperPilot Type | SPICE Prefix | Example |
|------------------|--------------|---------|
| resistor | R | `R1 node1 node2 10k` |
| capacitor | C | `C1 node1 node2 100nF` |
| inductor | L | `L1 node1 node2 33uH` |
| fuse | R (0.001Ω) | `RF1 node1 node2 0.001` |
| connector | R (0.001Ω) | `RJ1 node1 node2 0.001` |

### Semiconductors

| CopperPilot Type | SPICE Prefix | Example |
|------------------|--------------|---------|
| diode | D | `D1 anode cathode 1N4148` |
| led | D | `DLED1 anode cathode LED_GREEN` |
| zener | D | `DZ1 anode cathode BZX84C5V1` |
| npn | Q | `Q1 C B E 2N2222` |
| pnp | Q | `Q1 C B E 2N2907` |
| nmos | M | `M1 D G S B IRF540` |
| pmos | M | `M1 D G S B IRF9540` |

### ICs and Complex Components

| CopperPilot Type | SPICE Prefix | Example |
|------------------|--------------|---------|
| ic | X | `XU1 nodes... MODEL_NAME` |
| opamp | X | `XU1 INP INN VCC VEE OUT TL074` |
| regulator | X | `XU1 IN GND OUT LM7805` |

---

## Built-in Models

### Diodes

- **1N4148, 1N4007, 1N4001** - General purpose
- **1N5819, 1N5822, SS34, SS14** - Schottky
- **BZX84C5V1, BZX84C3V3** - Zener
- **SMBJ51A, SMBJ24A** - TVS
- **LED_RED, LED_GREEN, LED_BLUE** - LEDs

### Transistors

- **2N2222, 2N3904, BC547** - NPN
- **2N2907, 2N3906, BC557** - PNP
- **IRF540, IRF530, 2N7000, BS170** - N-MOSFET
- **IRF9540, IRF9530** - P-MOSFET

### Op-Amps

- **TL071, TL074** - JFET input
- **LM358** - General purpose
- **NE5532** - Low noise audio

### Voltage Regulators

- **LM7805, LM7812, LM7815** - Positive fixed
- **LM7915** - Negative fixed
- **LM317** - Adjustable
- **AMS1117-3.3, AMS1117-5.0** - LDO

---

## Module Architecture

```
scripts/
├── spice_converter.py          # Main entry point
└── spice/
    ├── __init__.py
    ├── model_library.py        # Component → SPICE mapping
    ├── netlist_generator.py    # .cir format output
    ├── ltspice_generator.py    # .asc schematic format
    └── simulation_validator.py # Parse results & validate
```

### Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `SpiceModelLibrary` | model_library.py | Component type detection and model selection |
| `SpiceNetlistGenerator` | netlist_generator.py | SPICE .cir file generation |
| `LTSpiceGenerator` | ltspice_generator.py | LTSpice .asc file generation |
| `SimulationValidator` | simulation_validator.py | Parse results, validate requirements |

---

## Simulation Validation (Advanced)

The `SimulationValidator` class can automatically validate simulation results against requirements:

```python
from scripts.spice.simulation_validator import SimulationValidator, ValidationRequirement

validator = SimulationValidator()

# Parse simulation output
validator.parse_raw_file("output/spice/circuit.raw")

# Define requirements
requirements = [
    ValidationRequirement(
        name="Bandwidth Check",
        check_type="bandwidth",
        target=50000,  # 50kHz
        tolerance_percent=10,
        unit="Hz"
    ),
    ValidationRequirement(
        name="Output Voltage Swing",
        check_type="voltage_swing",
        target=20,  # 20Vpp
        node="OUTPUT",
        unit="V"
    ),
]

# Validate
results = validator.validate_requirements(requirements)
report = validator.generate_report(results, "Power Amplifier")
print(report)
```

---

## Testing

```bash
# Run test suite
python tests/test_spice_converter.py

# Or with pytest
pytest tests/test_spice_converter.py -v
```

---

## Dependencies

### Required
- Python 3.10+
- CopperPilot virtual environment

### Optional (for simulation)
- **ngspice**: `brew install ngspice` (macOS) or `apt install ngspice` (Linux)
- **LTSpice**: Free download from [Analog Devices](https://www.analog.com/en/design-center/design-tools-and-calculators/ltspice-simulator.html)

---

## Design Principles

1. **GENERIC**: Works with ANY circuit type - from LED blinkers to complex multi-board systems
2. **MODULAR**: Each module has single responsibility
3. **EXTENSIBLE**: Easy to add new component models
4. **ROBUST**: Handles unknown components gracefully with fallback models
5. **WELL-DOCUMENTED**: Professional comments throughout code

---

## Ground Pattern Matching (February 2026 Fix)

The SPICE converter's net-to-node mapping was overhauled to eliminate false ground assignments.

### Problem

The original ground detection used substring matching (`'0' in net_upper`), which caused any net containing the digit `0` to map to node 0 (GND):
- `+180V_DC` matched because `180` contains `0` — **180V shorted to GND**
- `ADC_CH0` matched because `CH0` contains `0` — **ADC reads 0V permanently**

### Solution

Ground patterns are now structured as exact/prefix/suffix matching, loaded from `server/config.py`:

```python
SPICE_GROUND_PATTERNS = {
    "exact": {"GND", "GROUND", "VSS", "0", "0V", "DGND", "AGND", "PGND", ...},
    "prefixes": ["GND_", "GROUND_"],
    "suffixes": ["_GND", "_GROUND", "_VSS"],
}
```

Additional safety measures:
- **Power rail protection**: After mapping, any power rail accidentally assigned to node 0 is reassigned to a new sequential node
- **Unmapped net handling**: Nets not in the mapping table receive new sequential node numbers (never default to 0)
- All patterns configurable via `server/config.py` without code changes

---

## Troubleshooting

### "Model not found" errors

The converter generates generic subcircuit placeholders for unknown ICs. These may need manual replacement with actual SPICE models from:
- Manufacturer websites
- LTSpice built-in library
- Third-party SPICE model collections

### Simulation doesn't converge

1. Check for floating nodes (unconnected pins)
2. Add small resistors (1MΩ) to high-impedance nodes
3. Adjust simulation parameters (.options)

### Component values wrong

Check the source JSON file - the converter passes values directly to SPICE. Values like "470uF/63V" are automatically cleaned to "470uF".

### Components showing "0 0" node connections

If SPICE netlist shows components like `R1 0 0 10k`, it means both pins are connected to the same node (ground). This is a **circuit design issue** in the source JSON, not a converter issue.

**Symptoms:**
- SPICE file shows `R1 0 0 10k` or `C1 0 0 100nF`
- Simulation runs but components carry zero current
- Circuit behavior is wrong

**Root Cause:**
The `pinNetMapping` in the lowlevel JSON has both pins assigned to the same net:
```json
"R1.1": "GND",
"R1.2": "GND"  // WRONG - both pins on same net!
```

**Solution:**
1. The Circuit Supervisor now detects shorted passives via `_check_shorted_passives()`
2. The `ShortedPassiveFixer` automatically reassigns one pin to a different net
3. The Stage 2 AI prompt now includes LAW 4 requiring 2-terminal passives to bridge different nets

**To verify a circuit is correct:**
```python
from workflow.circuit_supervisor import CircuitSupervisor
supervisor = CircuitSupervisor()
issues = supervisor._check_shorted_passives(circuit)
print(f"Shorted passives: {len(issues)}")  # Should be 0
```

---

