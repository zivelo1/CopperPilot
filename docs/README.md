# CopperPilot

> AI-powered circuit design automation platform — from requirements to manufacturing-ready files in minutes.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com)

---

## Safety Disclaimer

AI-generated circuits require professional review and validation by a licensed electrical engineer before fabrication. CopperPilot is a design automation tool, not a substitute for professional engineering judgment.

---

## What is CopperPilot?

CopperPilot transforms natural-language circuit requirements into complete, validated design packages. It orchestrates Claude AI through a 7-step automated workflow that generates schematics, PCB layouts, BOMs, and export files for KiCad, Eagle, EasyEDA Pro, and SPICE — all from a single text or PDF specification.

### Key Features

- **End-to-End Automation** — Input requirements, receive a complete design package (schematics + PCB + BOM + exports)
- **Strict Architecture Contracts** — Step 2 produces typed interface specs with explicit isolation domains (e.g., GND_ISO, GND_USB)
- **Standardized Schematics** — High-fidelity PNG generation using standard IEEE/IEC symbol primitives and functional clustering
- **Multi-Format Export** — KiCad 9, Eagle XML, EasyEDA Pro, SPICE/LTSpice netlists
- **Dual-Supplier BOM** — Parallel Mouser + Digikey searches with side-by-side comparison
- **Multi-Agent Architecture** — Complex designs are decomposed into focused sub-tasks with specialized AI agents
- **Self-Healing Converters** — Automatic ERC/DRC validation with code-based fix loops
- **Design for Manufacturing (DFM)** — Validates against JLCPCB, PCBWay, and OSHPark fabrication rules
- **Real-Time Progress** — WebSocket-based live updates during generation
- **Web Interface** — Built-in frontend for submitting designs and monitoring progress

---

## Quick Start

### Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/settings/keys)
- (Optional) KiCad 9 for ERC/DRC validation
- (Optional) Mouser / Digikey API keys for BOM generation

### Installation

```bash
# Clone the repository
git clone https://github.com/<your-org>/CopperPilot.git
cd CopperPilot

# Run setup (creates venv and installs dependencies)
./setup.sh

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY (required)
```

### Running the Server

```bash
# Development mode (with auto-reload)
./start_server.sh --dev

# Production mode
./start_server.sh

# Stop the server
./stop_server.sh
```

Open http://localhost:8000 for the web interface, or http://localhost:8000/docs for the API documentation.

---

## Architecture

### 7-Step Workflow

```
Step 1: Information Gathering    — Parse requirements (text/PDF), ask clarifying questions
Step 2: High-Level Design        — Architecture decisions, module decomposition
Step 3: Circuit Generation       — Component selection + connection synthesis per module
Step 4: BOM Generation           — Dual-supplier part search (Mouser + Digikey)
Step 5: Format Conversion        — KiCad, Eagle, EasyEDA Pro, SPICE export with validation
Step 6: Quality Assurance        — ERC/DRC checks, DFM validation, self-healing fix loops
Step 7: Packaging                — ZIP archive with all outputs + assembly guide PDF
```

### Multi-Agent System

For complex designs (3+ modules), CopperPilot activates a hierarchical multi-agent architecture:

```
DesignSupervisor (orchestrator)
  └── ModuleAgent (per module)
        ├── ComponentAgent    — selects components with ratings
        ├── ConnectionAgent   — synthesizes connections between components
        └── ValidationAgent   — per-module ERC validation
  └── IntegrationAgent        — cross-module interface connections
```

### Project Structure

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
│   └── validators/       # ERC/DRC validation
├── frontend/             # Single-page web interface
├── tests/                # Test suite
├── docs/                 # Documentation
│   ├── Internal/         # Internal development notes
│   └── Test Prompts Examples/  # Sample circuit specifications
└── utils/                # Shared utilities (logging, helpers)
```

---

## Configuration

All configuration is managed through environment variables (`.env` file) and `server/config.py`.

### Required

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Server bind address |
| `DEBUG_MODE` | `false` | Enable debug logging |
| `MOUSER_API_KEY` | — | Mouser API key for BOM |
| `DIGIKEY_CLIENT_ID` | — | Digikey OAuth2 client ID |
| `DIGIKEY_CLIENT_SECRET` | — | Digikey OAuth2 client secret |
| `ALLOWED_ORIGINS` | `localhost` | CORS allowed origins (comma-separated) |
| `KICAD_CLI_PATH` | auto-detected | Path to KiCad CLI binary |

See [`.env.example`](.env.example) for the complete list.

### AI Model Configuration

CopperPilot uses three Claude model tiers, configured in `server/config.py`:

| Agent Role | Model | Rationale |
|-----------|-------|-----------|
| Circuit Design (Step 3) | Claude Opus 4.6 | Maximum intelligence for component selection |
| Architecture / Coding | Claude Sonnet 4.5 | Best balance of speed and quality |
| Validation | Claude Haiku 4.5 | Fast, cost-effective for deterministic checks |

See [`AI_MODEL_CONFIGURATION.md`](AI_MODEL_CONFIGURATION.md) for detailed model assignments per workflow step.

---

## API Reference

### Core Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/generate` | Start circuit generation |
| `POST` | `/api/generate/upload` | Start with PDF/image upload |
| `GET` | `/api/status/{id}` | Get generation progress |
| `GET` | `/api/download/{id}` | Download output package |
| `WS` | `/ws/{id}` | Real-time progress updates |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Interactive API documentation (Swagger) |

### Debug Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/debug/test-fix-logic` | Test fix pipeline without AI |
| `GET` | `/api/debug/{id}/{step}` | Inspect step inputs/outputs |
| `POST` | `/api/replay/{id}/{step}` | Replay a step with saved data |

---

## Testing

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=workflow --cov=scripts -v
```

See [`TESTING_GUIDE.md`](TESTING_GUIDE.md) for the complete testing guide.

---

## Documentation

| Document | Description |
|----------|-------------|
| [`AI_MODEL_CONFIGURATION.md`](AI_MODEL_CONFIGURATION.md) | Model assignments and cost analysis |
| [`EAGLE_CONVERTER.md`](EAGLE_CONVERTER.md) | Eagle CAD converter documentation |
| [`KICAD_CONVERTER.md`](KICAD_CONVERTER.md) | KiCad 9 converter documentation |
| [`EASYEDA_PRO_CONVERTER.md`](EASYEDA_PRO_CONVERTER.md) | EasyEDA Pro converter documentation |
| [`SPICE_CONVERTER.md`](SPICE_CONVERTER.md) | SPICE/LTSpice converter documentation |
| [`DUAL_SUPPLIER_BOM_SYSTEM.md`](DUAL_SUPPLIER_BOM_SYSTEM.md) | Mouser + Digikey BOM system |
| [`TESTING_GUIDE.md`](TESTING_GUIDE.md) | Test suite documentation |
| [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) | Technical architecture deep dive |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |
| [`QUALITY_BASELINE.md`](QUALITY_BASELINE.md) | Quality metrics and validation baseline |

---

## Known Limitations

| Area | Limitation | Workaround |
|------|-----------|------------|
| **KiCad ERC/DRC** | Requires KiCad 9 CLI (`kicad-cli`) installed locally for electrical validation. Without it, structural checks only — results show "UNVALIDATED". | Install KiCad 9 or set `KICAD_CLI_PATH` env var |
| **EasyEDA Pro** | Manhattan Router cannot reliably route dense circuits (40+ components). Experimental status. | Use KiCad or Eagle for complex designs |
| **SPICE Models** | Auto-generated SPICE models use behavioral approximations. 13 common ICs have pin-count-aware behavioral models. Pin ordering for MOSFET/BJT/DIODE/JFET is auto-corrected to SPICE standard order. NTC/PTC thermistors modeled as resistors. B-source syntax validated before output. High-frequency fidelity may vary. | Add `.lib` model files to the SPICE output directory for high-precision simulation |
| **Multi-Module Integration** | Cross-module interface signals have auto-reconciliation and fuzzy matching with config-driven pattern recognition (100+ patterns). Naming should remain as consistent as possible in requirements. | Review `SYS_*` nets in output and verify interface connectivity |
| **Component Ratings DB** | The ratings database (`data/component_ratings.json`) covers 177 common parts. Per-module voltage domain inference from power net names. | Add entries to the JSON file — no code changes needed |
| **AI Non-Determinism** | Same input can produce different quality results across runs. Quality improves with each release. Peak benchmark: 10/10 PERFECT modules across test cases of varying complexity. | Run multiple times and compare outputs; review all designs before fabrication |
| **Quality Gates** | Fail-closed quality gates may reject modules that are nearly correct. This is by design — false passes are more dangerous than false rejects. | Review fixer reports for specific issues; re-run if needed |

---

## Contributing

Contributions are welcome! Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for guidelines.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
