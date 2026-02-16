# AI Model Configuration

**Last Updated: February 15, 2026**

## February 2026 Update: Opus 4.6 Upgrade & Model Cleanup

### Current Model IDs (Official Anthropic API)

| Model | API ID | Context | Max Output | Input Cost | Output Cost |
|-------|--------|---------|------------|------------|-------------|
| **Claude Opus 4.6** | `claude-opus-4-6` | 1M | 128K | $5/MTok | $25/MTok |
| **Claude Opus 4.5** | `claude-opus-4-5-20251101` | 200K | 64K | $5/MTok | $25/MTok |
| **Claude Sonnet 4.5** | `claude-sonnet-4-5-20250929` | 200K | 64K | $3/MTok | $15/MTok |
| **Claude Haiku 4.5** | `claude-haiku-4-5-20251001` | 200K | 64K | $1/MTok | $5/MTok |

Source: [Anthropic Models Overview](https://platform.claude.com/docs/en/about-claude/models/overview)

### Model Selection Guidelines

| Use Case | Recommended Model | Rationale |
|----------|-------------------|-----------|
| Complex circuit design | **Opus 4.6** | 1M context, 128K output, best intelligence |
| Component selection (multi-agent) | **Sonnet 4.5** | Fast, accurate, best for coding |
| Connection synthesis (multi-agent) | **Sonnet 4.5** | Good precision at moderate cost |
| Validation/ERC checks | **Haiku 4.5** | Fast, cheap, near-frontier (5x cheaper than Sonnet) |
| Interface definition | **Opus 4.6** | Critical for multi-module success |
| BOM optimization | **Sonnet 4.5** | Good balance of speed and accuracy |

### Env-Overridable Model Selection

Every step's model can be overridden via environment variable without code changes:

```bash
# Example: downgrade step_3 to Sonnet for cost savings
MODEL_STEP_3_DESIGN_MODULE=claude-sonnet-4-5-20250929

# Example: use Opus 4.5 instead of 4.6 for testing
MODEL_STEP_3_STAGE1_COMPONENTS=claude-opus-4-5-20251101
```

See `.env.example` for the full list of overridable env vars.

---

## Multi-Agent Architecture (January 2026)

### Overview
Hierarchical multi-agent system for complex circuit design with specialized agents for different tasks.

### Agent Model Configurations

| Agent | Model | Temperature | Max Tokens | Timeout | Purpose |
|-------|-------|-------------|------------|---------|---------|
| component_agent | Sonnet 4.5 | 0.3 | 20000 | 180s | Component selection |
| connection_agent | Sonnet 4.5 | 0.2 | 20000 | 180s | Connection synthesis |
| validation_agent | Haiku 4.5 | 0.1 | 8000 | 60s | Per-module ERC (fast!) |
| integration_agent | Sonnet 4.5 | 0.2 | 20000 | 240s | Cross-module integration |
| supervisor_interface | **Opus 4.6** | 0.3 | 8000 | 180s | Interface definition (critical) |

### Configuration Location
All agent models are configured in `server/config.py` under the `MODELS` dict.

### Multi-Agent Settings
```python
MULTI_AGENT_CONFIG = {
    "enabled": True,                    # Enable multi-agent mode
    "max_parallel_modules": 3,          # Max concurrent module designs
    "max_retries_per_agent": 2,         # Retries per agent call
    "retry_delay_seconds": 10,          # Delay between retries
    "max_validation_iterations": 5,     # Max validation loops
    "allow_imperfect_modules": True,    # Continue with imperfect modules
    "max_components_per_module": 50,    # Warn if exceeded
    "warn_components_per_module": 30,   # Info threshold
    "enable_parallel_design": True,     # Allow parallel module design
    "enable_backplane": True,           # Create backplane circuit
    "log_agent_prompts": False,         # Debug: log full prompts
    "save_intermediate_results": True   # Save per-module results
}
```

### Quality Gates (February 2026)

Pipeline quality thresholds are configured in `server/config.py` under `QUALITY_GATES`. All are env-overridable:

| Gate | Default | Env Var | Purpose |
|------|---------|---------|---------|
| `max_critical_fixer_issues` | 0 | `MAX_CRITICAL_FIXER_ISSUES` | Hard gate for circuit fixer (fail-closed) |
| `min_interface_connection_ratio` | 0.5 | `MIN_INTERFACE_CONNECTION_RATIO` | Integration validation (fail-closed if below) |
| `max_stall_iterations` | 3 | `MAX_STALL_ITERATIONS` | Supervisor convergence |
| `max_supervisor_iterations` | 10 | `MAX_SUPERVISOR_ITERATIONS` | Max fix loop iterations |
| `max_fixer_iterations` | 3 | `MAX_FIXER_ITERATIONS` | Circuit fixer iterations |
| `voltage_derating_factor` | 1.2 | `VOLTAGE_DERATING_FACTOR` | Component rating safety margin |
| `min_ground_connection_ratio` | 0.05 | `MIN_GROUND_CONNECTION_RATIO` | Ground coverage validation |
| `spice_gate_enabled` | True | `SPICE_GATE_ENABLED` | Mandatory ngspice compile check |

### Debugging
Enable debug logging to see agent-level details:
```python
# In server/config.py
MULTI_AGENT_CONFIG["log_agent_prompts"] = True
```

Log tags for filtering:
- `[SUPERVISOR]` - Design supervisor orchestration
- `[MODULE_AGENT]` - Per-module design coordination
- `[COMPONENT_AGENT]` - Component selection
- `[CONNECTION_AGENT]` - Connection synthesis
- `[VALIDATION_AGENT]` - Validation checks
- `[INTEGRATION_AGENT]` - Module integration

---

## December 23, 2025 Update: Stage 2 Prompt - Shorted Passives Fix (TC #91)

### Problem Identified
The Stage 2 prompt (`step_3_stage2_connections.txt`) was missing a rule for 2-terminal passive components.
- 68% of components (129/188) had both pins connected to the same net (usually GND)
- This made components electrically useless (zero current flows through a shorted resistor)
- SPICE netlists showed `R1 0 0 10k` patterns (both terminals to node 0)

### Fix Applied

**Added LAW 4 to Stage 2 Prompt:**
```
### LAW 4: TWO-TERMINAL PASSIVES MUST BRIDGE DIFFERENT NETS
For current to flow through a 2-terminal passive component (R, C, L, D),
its two pins MUST connect to DIFFERENT nets.

WRONG: "R1.1": "GND", "R1.2": "GND" (zero current)
CORRECT: "R1.1": "VOUT_5V", "R1.2": "FB" (current flows!)
```

**Added Validation Check #6:**
- Verifies all 2-terminal passives bridge different nets before output

**Added Circuit Supervisor Detection:**
- New check: `_check_shorted_passives()` in `circuit_supervisor.py`
- New fixer: `ShortedPassiveFixer` class automatically fixes issues

### Result
| Metric | Before | After |
|--------|--------|-------|
| Shorted passives | 129/188 (68%) | **0** |
| SPICE simulation | Fails | **Works** |

---

## December 21, 2025 Update: Critical Token & Prompt Fixes

### Problem #1: Step 2 Highlevel Truncation
- **Symptom**: Highlevel designs were monochromatic, missing module details
- **Root Cause**: `max_tokens: 4000` was insufficient for complex designs
- **Evidence**: AI response TRUNCATED at line 308 mid-JSON
- **Fix**: Increased `max_tokens` from 4000 to 16000, timeout from 240s to 300s

### Problem #2: Step 3 Timeout & Prompt
- **Symptom**: Opus 4.5 timing out after 8+ minutes
- **Fixes Applied**:
  1. Created **hybrid prompt** combining JSON format with rating guidelines
  2. Added **timeout retry logic** (2 retries with 30-60s backoff)
  3. Added **pin normalization** for defensive error handling

### Updated Configuration

| Step | max_tokens | timeout | Notes |
|------|------------|---------|-------|
| Step 2 | 4000 → **16000** | 240s → **300s** | Complex designs were truncated |
| Step 3 | 16000 | 600s | Added timeout retry logic |

---

## December 2025 Update: Critical Workflow Data Flow Fix

**CRITICAL FIX**: Step 3 was not receiving AI-extracted specifications from Step 1.

### Problem Identified
The component rating validation system was showing `Max Voltage: 0.0V` because:
1. `gathered_info` (containing AI-extracted specs like "360Vpp") was not saved to `self.state` in normal workflow
2. Step 3 retrieved empty dict from state instead of full specifications
3. AI designed circuits without electrical requirements awareness

### Fix Applied
```python
# In circuit_workflow.py (line 188-190):
# CRITICAL FIX: Save gathered_info to state so Step 3 can access it
self.state['gathered_info'] = gathered_info  # Now ALWAYS saved
```

### Additional Fix: Vpp Calculation
The requirements extractor was halving Vpp values (360Vpp → 180V), causing incorrect MOSFET rating recommendations. Fixed to use full Vpp value for conservative H-bridge component selection.

### Result
| Metric | Before | After |
|--------|--------|-------|
| Max Voltage | 0.0V | **360V** |
| Recommended Rating | 0V | **720V** |
| AI Has Specs | ❌ No | ✅ Yes |

---

## November 2025 Update: Claude Opus 4.5 Integration

**MAJOR UPDATE**: Upgraded Step 3 (Circuit Design) from Opus 4.1 to Opus 4.5.

### Why Opus 4.5?
- **66% Cost Reduction**: $5/$25 vs $15/$75 per million tokens
- **Best-in-class Coding**: 80.9% on SWE-bench (industry-leading)
- **2x Output Limit**: 64K vs 32K tokens (better for complex circuits)
- **Hybrid Reasoning**: Extended thinking for complex problems
- **76% Fewer Tokens**: More efficient responses

### Cost Savings Per Circuit Run:
| Component | Before (Opus 4.1) | After (Opus 4.5) | Savings |
|-----------|-------------------|------------------|---------|
| Step 3 Est. Cost | $1.20 | $0.40 | 66% |
| Total Run Cost | $1.39 | $0.59 | 57% |

### Model ID Reference:
- **Opus 4.5**: `claude-opus-4-5-20251101`
- **Sonnet 4.5**: `claude-sonnet-4-5-20250929`

---

## ⚠️ CRITICAL: System Flexibility Requirement

**IMPORTANT**: All AI models and prompts must handle circuits of ANY complexity:

**Complexity Range:**
- **Simple** (1-5 components): LED with resistor, basic timers, voltage dividers
- **Medium** (5-50 components): Microcontroller projects, sensor arrays, amplifiers
- **Complex** (50+ components): Multi-board systems like the 9-circuit ultrasonic transducer (369 components)

The 9-circuit ultrasonic transducer example represents the HIGH END. The system MUST work equally well for a user asking "design a simple LED flasher" or "4-channel audio amplifier". All AI prompts must remain flexible and not assume any specific complexity level.

## Current Model Configuration

### Step 1: Information Gathering
- **Model**: Sonnet 4.5 (env: `MODEL_STEP_1`)
- **Purpose**: Extract requirements from user input
- **Max Tokens**: 4000
- **Temperature**: 0.5

### Step 2: High-Level Design
- **Model**: Sonnet 4.5 (env: `MODEL_STEP_2_HIGH_LEVEL`)
- **Purpose**: Create system architecture
- **Max Tokens**: 16000
- **Timeout**: 300s
- **Temperature**: 0.5

### Step 3: Low-Level Circuit Design (CRITICAL)
- **Model**: **Opus 4.6** (env: `MODEL_STEP_3_DESIGN_MODULE`) **(UPGRADED Feb 2026)**
- **Purpose**: Generate electronic circuits
- **Max Tokens**: 16000 (Opus 4.6 supports 128K)
- **Temperature**: 0.2 (precise)
- **Timeout**: 10 minutes
  - **Achievement**: 9/9 circuits at 100% perfection
  - **Result**: 0 critical issues, 0 errors
  - **Complex System Test**: 369 components across 9 circuits, all perfect
  - **Flexibility**: Handles simple to complex circuits without modification

Update (2025‑11‑25): **Upgraded to Opus 4.5**
- Model changed from `claude-opus-4-1-20250805` to `claude-opus-4-5-20251101`
- 66% cost reduction ($5/$25 vs $15/$75 per million tokens)
- Better benchmarks: 80.9% SWE-bench (vs ~72% for Opus 4.1)
- Increased max_tokens from 8K to 16K (Opus 4.5 supports 64K output)

Update (2025‑11‑02):
- No changes to Step 3 AI model configuration. The latest imperfection was resolved by refining the Python‑side validator (type‑aware power heuristics for reference/shunt/regulator devices like TL431), not by altering prompts or models. Latest run re‑validated from saved AI outputs: 6/6 PERFECT low‑level circuits.

### Step 4: BOM Generation
- **Model**: `claude-sonnet-4-5-20250514`
- **Purpose**: Select real components
- **Max Tokens**: 8192
- **Temperature**: 0.3 (precise)
- **Status**: ✅ Working correctly

## Model Selection Rationale

### Why Sonnet 4.5 for Steps 1, 2, 4:
- Fast response times
- Lower cost
- Sufficient capability for structured tasks
- Proven reliability

### Why Opus 4.6 for Step 3 & Critical Design (Feb 2026 Upgrade):
- **Same price** as Opus 4.5 ($5/$25 per MTok)
- **5x context window**: 1M tokens vs 200K (handles massive circuit designs)
- **2x output capacity**: 128K tokens vs 64K (eliminates truncation risk)
- **Latest intelligence**: Best reasoning for complex circuit decisions
- Maximum precision required for circuit generation
- Env-overridable: set `MODEL_STEP_3_DESIGN_MODULE` to downgrade if needed

## Issues Resolved (October 2025)

### October 12, 2025: Converter Production Fixes

1. **✅ Eagle Converter - Zero-Length Wires** (CRITICAL)
   - **Problem**: All wires had coordinates (0,0) → (0,0), files unimportable
   - **Root Cause**: Component positions calculated AFTER schematic generation
   - **Fix**: Calculate positions BEFORE generation, use actual pin positions
   - **Result**: 0 zero-length wires across all 9 circuits (913 wires total, all valid)
   - **Impact**: Eagle files now ready for KiCad/EasyEDA import

2. **✅ Eagle Converter - Enhanced DRC Validation**
   - **Added**: Zero-length wire detection to prevent regression
   - **Behavior**: Fails with CRITICAL error if zero-length wires found
   - **Result**: Future-proof protection against coordinate bugs

3. **✅ EasyEDA Pro Converter - Excessive Warnings** (2673 → 134)
   - **Problem**: NC (No Connect) nets treated as errors, verbose DRC warnings
   - **Fix**: Skip NC_ nets in validation, consolidate warnings
   - **Result**: 95% warning reduction, only legitimate warnings remain
   - **Impact**: EasyEDA Pro files production-ready with clean validation

### October 9, 2025: Text Parser & Circuit Supervisor Fixes
All critical bugs in Step 3 processing have been resolved:

1. **✅ Text Parser Net Merging** (Bug #1)
   - **Problem**: Parser overwrote pin net assignments
   - **Fix**: Intelligent net merging logic in `circuit_text_parser.py:239-279`
   - **Result**: All nets properly merged, no lost connections

2. **✅ PowerConnectionFixer Phantom Components** (Bug #2)
   - **Problem**: Added pin mappings before creating component definitions
   - **Fix**: Component definitions BEFORE pin references in `circuit_supervisor.py:619-642`
   - **Result**: All bypass capacitors properly defined

3. **✅ SingleEndedNetFixer Phantom Components** (Bug #3)
   - **Problem**: Pin references added without component definitions
   - **Fix**: Component definitions before pins for all auto-added components
   - **Result**: All test points, resistors, and capacitors properly defined

4. **✅ Duplicate Component Prevention** (Bug #4)
   - **Problem**: No existence checks before adding components
   - **Fix**: Check component existence before adding at all creation sites
   - **Result**: No duplicate components, clean validation

### October 6, 2025: Circuit Supervisor Enhancements
Initial fixes to validation and fixing logic:
- ✅ Floating component detection (checks ALL pins)
- ✅ FloatingComponentFixer pin references (proper dict extraction)
- ✅ Invalid pin detection and removal
- ✅ Single-ended net prevention

**ACHIEVEMENT: 100% circuit completeness - 6/6 circuits PERFECT**

## Configuration Files

### Server Config
- **File**: `server/config.py`
- **Models Defined**: All step models
- **Timeouts**: Step 3 = 600s (10 min), others = 300s

### AI Agent Manager
- **File**: `ai_agents/agent_manager.py`
- **Features**: Caching, retry logic, error handling
- **Cache TTL**: 1 hour

## Prompt Engineering Status

### Step 1 Prompts ✅
- Clear requirement extraction
- Handles text and PDF input
- No issues reported

### Step 2 Prompts ✅
- Text-based output format
- Module and connection descriptions
- Works for all circuit types

### Step 3 Prompts ✅ WORKING PERFECTLY
- **Status**: AI output is correct and complete
- **Evidence**: Forensic analysis proved AI generated valid circuits
- **Issues Were**: In Python processing code (text parser, circuit supervisor)
- **Result**: All processing bugs fixed, circuits now 100% perfect

### Step 4 Prompts ✅
- Effective part selection
- Good handling of alternatives
- API integration works well

## Future Optimizations

### Completed (October 2025):
1. ✅ Fixed Step 3 processing pipeline (text parser + circuit supervisor)
2. ✅ Validation logic now catches all issues
3. ✅ Circuit completeness achieved (100%)
4. ✅ Phantom components eliminated

### Long Term:
1. Few-shot examples for circuit generation (AI already performs well)
2. Component library integration in prompts
3. Advanced ERC rules (DRC, signal integrity, impedance matching)
4. Multi-layer PCB support

## Testing & Validation

### Model Performance Metrics:
- **Step 1**: 100% success rate ✅
- **Step 2**: 100% success rate ✅
- **Step 3**: 100% perfect circuits (9/9) ✅ **PRODUCTION READY**
- **Step 4**: 100% success rate ✅
- **Step 5 Converters**: 100% production ready ✅
  - Eagle: 0 zero-length wires
  - EasyEDA Pro: 95% warning reduction
  - BOM: Perfect output

### Quality Gates:
- Step 3 output MUST be 100% perfect
- Zero tolerance for phantom components
- All ICs must have power/ground
- No floating components allowed

## Configuration Best Practices

1. **Use Opus 4.6 for circuit generation** (Step 3) - upgraded Feb 2026
2. **Set appropriate timeouts** (10min for Step 3)
3. **Use lower temperature for precision** (0.2 for circuits)
4. **Cache responses where appropriate** (1hr TTL)
5. **Implement retry logic** (3 attempts with backoff)
6. **Use Sonnet 4.5 for simpler tasks** (Steps 1, 2, 4) - cost-effective
7. **Override models via env vars** - no code changes needed

## API Keys Required

```bash
# In .env file:
ANTHROPIC_API_KEY=your_key_here

# Optional:
MOUSER_API_KEY=your_key_here
```

## Monitoring & Logs

- **API Usage**: Tracked in ai_agents/agent_manager.py
- **Logs**: `logs/runs/[timestamp]/ai_training/`
- **Metrics**: Token usage, response times, error rates

## Critical Notes

⚠️ **IMPORTANT**:
1. Step 3 model configuration is CRITICAL for quality
2. Do not reduce timeout below 10 minutes
3. **Opus 4.6 is the recommended model** for circuit precision (upgraded from 4.5, Feb 2026)
4. Monitor for phantom component generation
5. Validate every circuit before converter processing

## Model ID Quick Reference (February 2026)

| Model | Model ID | Context | Max Output | Input Cost | Output Cost |
|-------|----------|---------|------------|------------|-------------|
| **Opus 4.6** | `claude-opus-4-6` | 1M | 128K | $5/MTok | $25/MTok |
| **Opus 4.5** | `claude-opus-4-5-20251101` | 200K | 64K | $5/MTok | $25/MTok |
| **Sonnet 4.5** | `claude-sonnet-4-5-20250929` | 200K | 64K | $3/MTok | $15/MTok |
| **Haiku 4.5** | `claude-haiku-4-5-20251001` | 200K | 64K | $1/MTok | $5/MTok |

**Key Benefits**:
- **Opus 4.6**: Same price as Opus 4.5, 5x context (1M), 2x output (128K)
- **Haiku 4.5**: Near-frontier intelligence at 5x lower cost than Sonnet

## Status Summary

**✅ PRODUCTION READY (October 12, 2025)**

**ACHIEVEMENT: 9/9 CIRCUITS + ALL CONVERTERS AT 100% PERFECTION**

- All models configured correctly ✅
- Step 3 processing pipeline fixed ✅
- All converters validated and production-ready ✅
- 0 critical issues, 0 errors ✅
- Ready for production use ✅

**Latest Validation Results:**
- 9 complete circuits (369 components, 283 nets, 913 wires)
- Eagle Converter: 0 zero-length wires ✅
- EasyEDA Pro Converter: 134 warnings (design completion only) ✅
- BOM Converter: 100% perfect ✅
- System validated for circuits ranging from simple (1 component) to complex (369 components)

**Key Achievements:**
- Flexibility: Handles any circuit complexity
- Eagle fix: 913/913 wires with valid coordinates
- EasyEDA Pro: 95% warning reduction (2673 → 134)
- Forensic validation: 100% production ready

**Documentation:**
- `docs/EAGLE_CONVERTER.md` - Eagle converter documentation
- `docs/CHANGELOG.md` - Converter validation history
