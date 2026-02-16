# BOM Converter

Aggregates components from lowlevel circuits into a normalized Bill of Materials and exports to multiple formats (CSV, HTML, JSON, TXT). Optionally fetches real-time pricing from Mouser and Digikey.

---

## Input / Output

| Direction | Path |
|-----------|------|
| **Input** | `output/<run-id>/lowlevel/components.csv` |
| **Output** | `output/<run-id>/bom/BOM.{csv,html,json,txt}` |
| | `output/<run-id>/bom/Mouser.html` — supplier pricing |
| | `output/<run-id>/bom/Digikey.html` — supplier pricing |
| | `output/<run-id>/bom/BOM_Comparison.html` — side-by-side comparison |

## Features

- **Package-Aware Grouping** — Components are grouped by `{type}_{value}_{package}`. Same-value components with different packages are listed as separate BOM lines.
- **Dual-Supplier Pricing** — Parallel Mouser + Digikey API searches with side-by-side comparison report.
- **User-Focused HTML** — Summary cards, datasheet links, "TBD" for missing prices. Internal columns (Stock, ID) are hidden.
- **Flexible Parsing** — Accepts both `Reference` and `RefDes` columns with robust range compression.

## Code Location

| File | Responsibility |
|------|---------------|
| `workflow/step_4_bom.py` | Main BOM orchestration, HTML generation |
| `scripts/bom_converter.py` | Component grouping and export logic |

See also: [DUAL_SUPPLIER_BOM_SYSTEM.md](DUAL_SUPPLIER_BOM_SYSTEM.md) for the full dual-supplier architecture.

## Supplier API Diagnostics (February 2026)

### Connection Testing

The `SupplierManager` now provides a `test_connections()` method that validates API connectivity for both Mouser and Digikey before starting bulk searches. Individual APIs also expose `test_connection()` for targeted checks.

```python
manager = SupplierManager()
status = manager.test_connections()
# {'mouser': True, 'digikey': False}
```

### Search Summary

After a BOM run, `write_search_summary()` writes a JSON report to the BOM output directory with per-supplier statistics:

```json
{
  "statistics": {
    "mouser_searches": 73,
    "mouser_results": 365,
    "mouser_errors": 0,
    "mouser_success_rate": 100.0,
    "digikey_searches": 73,
    "digikey_results": 438,
    "digikey_errors": 2,
    "digikey_success_rate": 97.3
  }
}
```

### Structured Logging

All supplier API modules now use `utils.logger` instead of `print()`. HTTP status codes and response bodies are logged on failure for easier debugging.

**Code locations:**
- `workflow/supplier_apis/mouser_api.py` — `test_connection()`, structured error logging
- `workflow/supplier_apis/digikey_api.py` — `test_connection()`
- `workflow/supplier_apis/supplier_manager.py` — `test_connections()`, `write_search_summary()`

---

## Multi-Agent Circuit Loading (February 2026 Fix)

In the multi-agent design path, Step 4 receives lightweight circuit references (with a `filepath` key) instead of full circuit data. The `_extract_all_components()` method now:

1. Detects lightweight references by checking for a `filepath` key without `components`
2. Loads the full circuit JSON from disk
3. Skips `circuit_integrated_circuit.json` (mega-module eliminated in pipeline)
4. Handles missing or corrupt files gracefully with warnings

This fix restored BOM extraction from 0 components to the full count in multi-agent runs.

---

## Future Enhancements

- Add LCSC / Arrow / Newark supplier options
- Supplier mode logging clarity (dual vs fallback)
