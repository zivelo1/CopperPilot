# Schematics Converter

Generates human-readable schematic PNGs and wiring description text files for each lowlevel circuit module.

---

## PNG Converter

### Input / Output

| Direction | Path |
|-----------|------|
| **Input** | `output/<run-id>/lowlevel/circuit_*.json` |
| **Output** | `output/<run-id>/schematics/circuit-<module-name>.png` |

### Features

- **Standard Symbol Engine** — Maps component types to **IEEE/IEC standard primitives** (zigzag resistors, parallel-plate capacitors, triangular op-amps).
- **Domain-Aware Placement** — Components are clustered based on their **Isolation Domain** (e.g., all high-voltage components grouped separately from low-voltage logic).
- **Weight-Based Force Clustering** — Physically groups components that share high net-counts (e.g., decoupling caps are automatically placed adjacent to their target IC).
- **Tiered Wiring Instructions** — `schematics_desc` output is prioritized by function: Power Distribution → Primary Signal Path → Auxiliary Logic.
- **Clear, labeled diagrams** with consistent styling and hyphenated filenames.
- **Dynamic canvas sizing** — adapts to component layout with optimized padding.
- **A* wire routing** with optimized parameters (`grid_size=20`, `max_iterations=25000`).
- **Precise wire-crossing detection** (line-segment vs component-body intersection).
- **Unconnected pin handling** — automatically detected and suppressed from warnings.

### Architecture

| Module | File | Purpose |
|--------|------|---------|
| Symbol Engine | `scripts/schematics/modules/symbol_library.py` | Maps component metadata to vector primitives (IEEE standards) |
| Layout Engine | `scripts/schematics/modules/layout_engine_fixed.py` | Domain-aware component placement, functional clustering |
| Wire Router | `scripts/schematics/modules/wire_router_astar.py` | A* pathfinding for wire routing |
| Validator | `scripts/schematics/modules/validator.py` | Connectivity and wire crossing checks |
| Input Processor | `scripts/schematics/modules/input_processor.py` | JSON parsing, isolation domain extraction |
| Utilities | `scripts/schematics/modules/utils.py` | Geometry helpers, `Wire`/`Pin` classes |

### Usage

```bash
python3 scripts/schematics_converter.py output/<run-id>/lowlevel output/<run-id>/schematics
```

---

## Text Converter (Wiring Descriptions)

### Input / Output

| Direction | Path |
|-----------|------|
| **Input** | `output/<run-id>/lowlevel/circuit_*.json` |
| **Output** | `output/<run-id>/schematics_desc/circuit_*_wiring.txt` |

### Features

- Component lists with reference designators
- Step-by-step connection instructions
- Embedded ERC/DRC summaries
- Key net mention checks (GND, VCC, signal outputs)

## Error Logging and Diagnostics (February 2026)

### File-Based Error Logger

The converter now writes persistent error logs to `{output_dir}/schematics_errors.log` for post-mortem analysis. All pipeline errors, stage timing, and circuit metadata are captured.

**Log contents:**
- Circuit file sizes (for large-circuit diagnostics)
- Per-stage timing (`InputProcessor`, `LayoutEngine`, `WireRouter`, `Renderer`, `Validator`)
- Validation error counts
- Component/net counts per circuit
- Full tracebacks for unexpected failures

### Per-Stage Timing

Each pipeline stage is individually timed. Example log output:
```
2026-02-07 12:00:01 [INFO] Processing power-supply-module: 45.2 KB
2026-02-07 12:00:01 [INFO]   power-supply-module | InputProcessor: 0.03s
2026-02-07 12:00:01 [INFO]   power-supply-module | LayoutEngine: 0.15s
2026-02-07 12:00:02 [INFO]   power-supply-module | WireRouter: 1.24s
2026-02-07 12:00:02 [INFO]   power-supply-module | Renderer: 0.08s
2026-02-07 12:00:02 [INFO]   power-supply-module | Validator: 0.02s
2026-02-07 12:00:02 [INFO]   power-supply-module | SUCCESS: 34 components, 13 nets
```

**Code location:** `scripts/schematics_converter.py` — `_setup_error_logger()` and `_process_single_circuit()`

---

## Future Enhancements

- SVG export for higher fidelity vector output
- Per-net grouping with cross-references to schematic coordinates
- Sidecar manifest (JSON/DOT) for graph-level parity checks
