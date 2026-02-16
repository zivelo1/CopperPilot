# Contributing to CopperPilot

Thank you for your interest in contributing! This guide will help you get started.

---

## Development Setup

```bash
# Clone and set up
git clone https://github.com/<your-org>/CopperPilot.git
cd CopperPilot
./setup.sh

# Activate the virtual environment
source venv/bin/activate

# Install development dependencies
pip install -r requirements-dev.txt

# Configure environment
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

## Code Style

This project uses the following tools for code quality:

- **[Black](https://black.readthedocs.io/)** — Code formatting (line length: 120)
- **[Flake8](https://flake8.pycqa.org/)** — Linting
- **[mypy](https://mypy-lang.org/)** — Type checking

```bash
# Format code
black .

# Check linting
flake8 .

# Run type checks
mypy server/ workflow/
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=workflow --cov=scripts -v

# Run a specific test file
pytest tests/test_circuit_supervisor.py -v
```

All new features should include tests. Bug fixes should include a regression test when practical.

## Pull Request Process

1. **Fork** the repository and create a feature branch from `main`
2. **Make your changes** following the code style guidelines above
3. **Add tests** for new functionality
4. **Run the test suite** to ensure nothing is broken
5. **Submit a PR** with a clear description of the changes

### PR Title Convention

Use a descriptive title that starts with a verb:
- `Add support for Altium export format`
- `Fix BOM quantity aggregation for multi-package components`
- `Update KiCad converter to support v9.1 format changes`

### PR Description

Include:
- **What** changed and **why**
- Any **breaking changes**
- How to **test** the changes

## Project Structure

| Directory | Responsibility |
|-----------|---------------|
| `server/` | FastAPI server, configuration |
| `workflow/` | 7-step workflow orchestration, multi-agent system |
| `ai_agents/` | AI agent manager, prompt templates |
| `scripts/` | Format converters (KiCad, Eagle, EasyEDA, SPICE, BOM) |
| `tests/` | Test suite |
| `docs/` | Documentation |
| `frontend/` | Web interface |
| `utils/` | Shared utilities |

## Reporting Issues

When reporting a bug, please include:
- Python version and OS
- Steps to reproduce the issue
- Expected vs actual behavior
- Relevant log output (from `logs/`)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
