# CopperPilot — Technical Architecture Overview

**AI-powered circuit design automation: from requirements to manufacturing-ready files.**

---

## System Architecture

CopperPilot orchestrates Claude AI through a 7-step automated pipeline that transforms natural-language circuit requirements into complete, validated design packages.

### 7-Step Workflow

| Step | Name | Description |
|------|------|-------------|
| 1 | Information Gathering | Parse requirements from text/PDF, ask clarifying questions |
| 2 | High-Level Design | Architecture decisions, module decomposition, isolation domains |
| 3 | Circuit Generation | Component selection + connection synthesis per module |
| 4 | BOM Generation | Dual-supplier part search (Mouser + Digikey) |
| 5 | Format Conversion | KiCad, Eagle, EasyEDA Pro, SPICE export with validation |
| 6 | Quality Assurance | ERC/DRC checks, DFM validation, self-healing fix loops |
| 7 | Packaging | ZIP archive with all outputs + QA report |

### Multi-Agent System

For complex designs (3+ modules), CopperPilot activates a hierarchical multi-agent architecture that decomposes the design problem into focused sub-tasks:

```
DesignSupervisor (orchestrator)
  └── ModuleAgent (per module)
        ├── ComponentAgent    — selects components with ratings
        ├── ConnectionAgent   — synthesizes connections between components
        └── ValidationAgent   — per-module ERC validation
  └── IntegrationAgent        — cross-module interface connections
```

**Benefits:**
- **Context isolation**: Each agent handles 20-50 components max (vs 200+ in single-agent mode)
- **Parallel design**: Independent modules designed concurrently
- **Graceful degradation**: Failed modules don't crash entire design
- **Interface contracts**: Well-defined module boundaries with typed interface specs

Multi-agent is configurable via `server/config.py` (`MULTI_AGENT_CONFIG`).

---

## Key Subsystems

### Circuit Supervisor (`workflow/circuit_supervisor.py`)

The supervisor validates every generated circuit against a comprehensive set of electrical rules:

- **Floating component detection** — all pins must be connected or marked NC
- **Shorted passive detection** — LAW 4: two-pin passives must bridge different nets
- **IC power connection verification** — active devices must have power and ground
- **Single-ended net detection** — nets with only one connection point
- **Pin function mismatch detection** — gate on power rail, drain-source short
- **Feedback divider accuracy** — Vout = Vref * (1 + Rtop/Rbottom) within tolerance
- **Component rating validation** — voltage derating per module voltage domain

All pattern matching is config-driven via `server/config.py` — no hardcoded values.

### Integration Agent (`workflow/agents/integration_agent.py`)

Handles cross-module connectivity for multi-agent designs:

- **Same-name net auto-merge** — nets appearing in 2+ modules with identical names are automatically shared
- **External input classification** — system-boundary inputs (VIN, MAINS) excluded from connection ratio
- **Self-contained signal recognition** — signals with 2+ internal connections not penalized as unmatched
- **Physical port audit** — validates every global net connects to a physical connector/test point
- **Hardware prefix stripping** — semantic matching (e.g., `ADC1_AIN0` → `AIN0`) via configurable prefix list

### Circuit Postprocessor (`workflow/circuit_postprocessor.py`)

Deterministic fixes applied after AI generation:

- **LAW 4 auto-fix** — moves shorted passive pins to `{net}_B`
- **Design artifact removal** — strips AI thinking leftovers (`Q1_REPLACED`, `R3_OLD`, `DNP`)
- **Config-driven** via `DESIGN_ARTIFACT_REF_SUFFIXES` and `DESIGN_ARTIFACT_VALUE_KEYWORDS`

### Rating Validator (`workflow/component_rating_validator.py`)

Per-module voltage domain validation:

- Infers operating voltage from power net names (including xVy notation: 3V3 → 3.3V)
- External ratings database: `data/component_ratings.json` (177 entries, user-extensible)
- 1.2x voltage derating factor (configurable)
- Config pin exemptions (ADDR/MODE/SEL/CFG pins tied to rails)

---

## Format Converters

### KiCad 9 (Production Ready)

**Output**: `.kicad_sch`, `.kicad_pcb`, `.kicad_pro`

Full conversion pipeline: annotation → placement → netlist sync → file generation → Manhattan routing → ERC/DRC validation → self-healing fix loop.

Key features:
- Label-only schematic connectivity (zero wire ERC errors)
- Pure Python Manhattan router with collision-free grid routing
- KiCad footprint library integration (exact pad dimensions from `.kicad_mod` files)
- IPC-7351B compliant pad dimensions
- Fail-closed quality gates
- Optional KiCad CLI validation for full ERC/DRC

See [`KICAD_CONVERTER.md`](KICAD_CONVERTER.md) for full documentation.

### Eagle CAD (Experimental)

**Output**: `.sch`, `.brd`, `.lbr`

Minimum Spanning Tree (MST) wire routing with pin-to-pin physical connections. Self-healing fix loop (2 code + 2 AI attempts). Works well for simple circuits; complex multi-module designs may encounter symbol mapping limitations.

See [`EAGLE_CONVERTER.md`](EAGLE_CONVERTER.md) for full documentation.

### EasyEDA Pro (Experimental)

**Output**: `.epro`

Self-healing architecture with Manhattan router. Dense circuits (40+ components) may experience routing congestion. Recommended for simple to moderate circuits (<30 components).

See [`EASYEDA_PRO_CONVERTER.md`](EASYEDA_PRO_CONVERTER.md) for full documentation.

### SPICE / LTSpice (Production Ready)

**Output**: `.cir` (SPICE netlist), `.asc` (LTSpice schematic)

Behavioral simulation support with:
- Pin ordering correction (MOSFET D/G/S/B, BJT C/B/E, Diode A/K)
- 13 pin-count-aware behavioral IC models
- NTC/PTC thermistor, ferrite bead, potentiometer, and connector models
- Structured ground pattern matching (eliminates false GND mapping)
- SPICE syntax pre-validation (B-source, pin count checks)
- Mandatory ngspice compile gate

See [`SPICE_CONVERTER.md`](SPICE_CONVERTER.md) for full documentation.

### BOM (Production Ready)

**Output**: CSV, HTML, JSON

Dual-supplier parallel search (Mouser + Digikey) with side-by-side comparison. Package-aware grouping. See [`DUAL_SUPPLIER_BOM_SYSTEM.md`](DUAL_SUPPLIER_BOM_SYSTEM.md).

### Schematics (Production Ready)

**Output**: PNG diagrams + text wiring descriptions

IEEE/IEC symbol primitives, functional clustering by isolation domain, tiered connection documentation (Power → Signal → Auxiliary). See [`SCHEMATICS_CONVERTER.md`](SCHEMATICS_CONVERTER.md).

---

## Quality Assurance

### Fail-Closed Architecture

Every circuit must pass all quality gates before release:

1. **Circuit Supervisor** — 0 critical issues required (`PERFECT` status)
2. **Component Ratings** — all components meet voltage derating requirements
3. **Integration Connectivity** — minimum connection ratio for cross-module signals
4. **SPICE Compile** — netlists must pass ngspice syntax and matrix sanity check
5. **Converter Validation** — ERC/DRC/DFM checks per format

Quality gate defaults are fail-closed: `fixer_gate_passed = False`, `integration_gate_passed = False`.

### Semantic Taxonomy

Component classification uses a hierarchical taxonomy in `server/config.py`:

- **`SEMANTIC_TAXONOMY`** — categorizes components (IC, passive, electromechanical, etc.)
- **`NON_ACTIVE_COMPONENT_TYPES`** — 36+ types that don't require power pins (connectors, switches, terminals)
- **`TWO_PIN_PASSIVE_TYPES`** — types subject to LAW 4 (shorted passive) checks

This eliminates false-positive power errors for passive connectors, mechanical switches, and thermal devices.

### Design Prompts

AI design prompts enforce structural rules:
- **LAW 4** — two-pin passives must bridge different nets (expanded to all passive types)
- **LAW 5** — no pin-reference net names
- **No Naked Auxiliaries** — all IC auxiliary pins (filter, compensation, bias, bootstrap, etc.) must have external passives
- **Net verification table** — mandatory source + destination for every internal signal

---

## Configuration

All configuration lives in `server/config.py` — single source of truth, zero duplication across consumers.

### Key Config Categories

| Category | Examples |
|----------|---------|
| **Pattern Sets** | `POWER_RAIL_PATTERNS`, `INTERFACE_NET_PATTERNS`, `SINGLE_ENDED_EXEMPT_PATTERNS` |
| **Component Types** | `ACTIVE_COMPONENT_TYPES`, `NON_ACTIVE_COMPONENT_TYPES`, `TWO_PIN_PASSIVE_TYPES` |
| **SPICE** | `SPICE_GROUND_PATTERNS`, `SPICE_POWER_SOURCE_PATTERNS`, `BEHAVIORAL_MODEL_PIN_MAP` |
| **Quality Gates** | `QUALITY_GATES`, `FEEDBACK_DIVIDER_TOLERANCE`, `ISSUE_SEVERITY` |
| **Integration** | `INTEGRATION_HARDWARE_PREFIXES_TO_STRIP`, `EXTERNAL_INPUT_NET_PATTERNS` |
| **AI Models** | Model assignments per workflow step (see [`AI_MODEL_CONFIGURATION.md`](AI_MODEL_CONFIGURATION.md)) |

All thresholds are environment-variable overridable.

---

## Project Structure

```
CopperPilot/
├── server/              # FastAPI server, configuration, entry points
├── workflow/             # 7-step workflow orchestration
│   ├── agents/           # Multi-agent system (supervisor, module, integration)
│   ├── supplier_apis/    # Mouser + Digikey API clients
│   └── dfm/              # Design for Manufacturing validation
├── ai_agents/            # AI agent manager + prompt templates
│   └── prompts/          # All AI prompt files (Step 1-4, fixers, multi-agent)
├── scripts/              # Format converters (KiCad, Eagle, EasyEDA, SPICE, BOM)
│   ├── kicad/            # KiCad-specific modules (placer, router, annotator)
│   ├── eagle/            # Eagle-specific modules
│   ├── easyeda/          # EasyEDA Pro modules
│   ├── routing/          # Manhattan router, progressive routing
│   ├── schematics/       # Schematic PNG generator
│   ├── spice/            # SPICE model library, netlist generator
│   └── validators/       # ERC/DRC/DFM validation
├── frontend/             # Single-page web interface
├── tests/                # Test suite (26 scripts, pytest integration)
├── docs/                 # Documentation
├── data/                 # Component ratings DB, IPC pad dimensions
└── utils/                # Shared utilities (logging, helpers)
```

---

## Design Principles

1. **Generic** — works for any circuit topology, no hardcoded component types or board sizes
2. **Modular** — each module independently testable with clear interfaces
3. **Dynamic** — configuration-driven parameters, adaptive timeouts, progressive fallbacks
4. **Fail-Closed** — zero critical errors required for pass, any failure triggers quarantine
5. **Single Source of Truth** — all patterns centralized in `config.py`, no duplication across consumers
6. **Manufacturing-First** — IPC-7351B pads, JLCPCB/PCBWay/OSHPark DFM profiles, real ERC/DRC validation

---

## AI Model Configuration

CopperPilot uses three Claude model tiers:

| Agent Role | Model | Rationale |
|-----------|-------|-----------|
| Circuit Design (Step 3) | Claude Opus 4.6 | Maximum intelligence for component selection |
| Architecture / Coding | Claude Sonnet 4.5 | Best balance of speed and quality |
| Validation / Fixing | Claude Haiku 4.5 | Fast, cost-effective for deterministic checks |

See [`AI_MODEL_CONFIGURATION.md`](AI_MODEL_CONFIGURATION.md) for detailed model assignments.

---

## Safety

AI-generated circuits require professional review and validation by a licensed electrical engineer before fabrication. CopperPilot is a design automation tool, not a substitute for professional engineering judgment.
