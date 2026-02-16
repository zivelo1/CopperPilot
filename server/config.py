# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Configuration module for Circuit Design Automation Server
Handles environment variables and settings
"""
import os
import platform
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class ModelType(Enum):
    """Anthropic model identifiers (February 2026).

    Current Models:
    - OPUS_4_6: Most intelligent, 1M context, 128K output ($5/$25 per MTok)
    - OPUS_4_5: Previous Opus, 200K context, 64K output ($5/$25 per MTok)
    - SONNET_4_5: Best speed/quality balance, great for coding ($3/$15 per MTok)
    - HAIKU_4_5: Fastest, cheapest, near-frontier intelligence ($1/$5 per MTok)

    See: https://platform.claude.com/docs/en/about-claude/models/overview
    """
    OPUS_4_6 = "claude-opus-4-6"              # Latest Opus — 1M context, 128K output
    OPUS_4_5 = "claude-opus-4-5-20251101"     # Previous Opus — 200K context, 64K output
    SONNET_4_5 = "claude-sonnet-4-5-20250929" # Best coding model, fast
    HAIKU_4_5 = "claude-haiku-4-5-20251001"   # Fastest, cheapest, near-frontier

def _kicad_default_paths() -> Dict[str, str]:
    """Return OS-appropriate default paths for KiCad installation.

    Supports macOS, Linux, and Windows. Override any path via environment
    variables: KICAD_LIBRARY_PATH, KICAD_SYMBOL_PATH, KICAD_CLI_PATH.
    """
    system = platform.system()
    if system == "Darwin":
        base = "/Applications/KiCad/KiCad.app/Contents"
        return {
            "library": f"{base}/SharedSupport/footprints",
            "symbols": f"{base}/SharedSupport/symbols",
            "cli": f"{base}/MacOS/kicad-cli",
        }
    if system == "Linux":
        return {
            "library": "/usr/share/kicad/footprints",
            "symbols": "/usr/share/kicad/symbols",
            "cli": "/usr/bin/kicad-cli",
        }
    # Windows
    return {
        "library": "C:/Program Files/KiCad/share/kicad/footprints",
        "symbols": "C:/Program Files/KiCad/share/kicad/symbols",
        "cli": "C:/Program Files/KiCad/bin/kicad-cli.exe",
    }


class Config:
    """Central configuration class"""

    # Base paths
    BASE_DIR = Path(__file__).parent.parent
    STORAGE_DIR = BASE_DIR / "storage"
    PROJECTS_DIR = STORAGE_DIR / "projects"
    LOGS_DIR = STORAGE_DIR / "logs"

    # Output folder structure (matching N8N)
    OUTPUT_DIR = BASE_DIR / "output"  # Points to Electronics/output folder

    # Converter scripts location
    SCRIPTS_DIR = BASE_DIR / "scripts"  # Points to Electronics/scripts folder

    # Ensure directories exist
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # API Configuration
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    # Parts API Configuration
    MOUSER_API_KEY = os.getenv("MOUSER_API_KEY", "")
    DIGIKEY_CLIENT_ID = os.getenv("DIGIKEY_CLIENT_ID", "")
    DIGIKEY_CLIENT_SECRET = os.getenv("DIGIKEY_CLIENT_SECRET", "")

    # =========================================================================
    # MODEL CONFIGURATION
    # =========================================================================
    # Every step's model is env-overridable via MODEL_<STEP_NAME_UPPER>.
    # Example: MODEL_STEP_3_DESIGN_MODULE=claude-sonnet-4-5-20250929
    #
    # Tier strategy:
    #   Opus 4.6  — critical circuit design (accuracy over speed)
    #   Sonnet 4.5 — supporting tasks (good speed/quality balance)
    #   Haiku 4.5  — validation & lightweight checks (fastest, cheapest)
    # =========================================================================
    MODELS = {
        "step_1": {
            "model": os.getenv("MODEL_STEP_1", ModelType.SONNET_4_5.value),
            "temperature": 0.5,
            "max_tokens": 4000,
            "timeout": 240  # 4 minutes
        },
        "step_2_high_level": {
            "model": os.getenv("MODEL_STEP_2_HIGH_LEVEL", ModelType.OPUS_4_6.value),
            "temperature": 0.5,
            "max_tokens": 16000,
            "timeout": 300  # 5 minutes
        },
        "step_3_extract_modules": {
            "model": os.getenv("MODEL_STEP_3_EXTRACT_MODULES", ModelType.SONNET_4_5.value),
            "temperature": 0.3,
            "max_tokens": 2000,
            "timeout": 240  # 4 minutes
        },
        "step_3_design_module": {
            "model": os.getenv("MODEL_STEP_3_DESIGN_MODULE", ModelType.OPUS_4_6.value),
            "temperature": 0.2,  # Low temperature for precision in circuit design
            "max_tokens": 16000,  # Opus 4.6 supports 128K output
            "timeout": 600,  # 10 minutes — CRITICAL for complex circuits
        },
        # Two-stage design: Stage 1 = component selection, Stage 2 = connections
        "step_3_stage1_components": {
            "model": os.getenv("MODEL_STEP_3_STAGE1_COMPONENTS", ModelType.OPUS_4_6.value),
            "temperature": 0.2,
            "max_tokens": 16000,  # Opus 4.6 supports 128K output
            "timeout": 300  # 5 minutes — focused task completes faster
        },
        "step_3_stage2_connections": {
            "model": os.getenv("MODEL_STEP_3_STAGE2_CONNECTIONS", ModelType.OPUS_4_6.value),
            "temperature": 0.2,
            "max_tokens": 16000,  # S.1 FIX: Matched to Stage 1 — complex modules need full token budget for JSON output
            "timeout": 300,  # 5 minutes
        },
        "step_3_fix_circuit": {
            "model": os.getenv("MODEL_STEP_3_FIX_CIRCUIT", ModelType.SONNET_4_5.value),
            "temperature": 0.5,
            "max_tokens": 8000,
            "timeout": 600  # 10 minutes — fixing can be iterative
        },
        "step_4_select_part": {
            "model": os.getenv("MODEL_STEP_4_SELECT_PART", ModelType.SONNET_4_5.value),
            "temperature": 0.2,
            "max_tokens": 2000,
            "timeout": 240  # 4 minutes
        },
        "step_4_optimize_bom": {
            "model": os.getenv("MODEL_STEP_4_OPTIMIZE_BOM", ModelType.SONNET_4_5.value),
            "temperature": 0.3,
            "max_tokens": 4000,
            "timeout": 240  # 4 minutes
        },
        "module_consolidation": {
            "model": os.getenv("MODEL_MODULE_CONSOLIDATION", ModelType.OPUS_4_6.value),
            "temperature": 0.2,
            "max_tokens": 16000,  # Opus 4.6 supports 128K output
            "timeout": 240  # 4 minutes
        },
        # =====================================================================
        # MULTI-AGENT ARCHITECTURE (January 2026)
        # Each agent has focused responsibilities with limited context.
        # =====================================================================
        "component_agent": {
            "model": os.getenv("MODEL_COMPONENT_AGENT", ModelType.OPUS_4_6.value),
            "temperature": 0.3,
            "max_tokens": 20000,
            "timeout": 180  # 3 minutes
        },
        "connection_agent": {
            "model": os.getenv("MODEL_CONNECTION_AGENT", ModelType.SONNET_4_5.value),
            "temperature": 0.2,
            "max_tokens": 20000,
            "timeout": 180  # 3 minutes
        },
        "validation_agent": {
            "model": os.getenv("MODEL_VALIDATION_AGENT", ModelType.HAIKU_4_5.value),
            "temperature": 0.1,
            "max_tokens": 8000,
            "timeout": 60  # 1 minute — Haiku is very fast
        },
        "integration_agent": {
            "model": os.getenv("MODEL_INTEGRATION_AGENT", ModelType.SONNET_4_5.value),
            "temperature": 0.2,
            "max_tokens": 20000,
            "timeout": 240  # 4 minutes
        },
        "supervisor_interface": {
            "model": os.getenv("MODEL_SUPERVISOR_INTERFACE", ModelType.OPUS_4_6.value),
            "temperature": 0.3,
            "max_tokens": 8000,
            "timeout": 180  # 3 minutes
        },
    }

    # =========================================================================
    # MULTI-AGENT ARCHITECTURE CONFIGURATION (January 2026)
    # =========================================================================
    # This configuration controls the hierarchical multi-agent circuit design
    # system. The system addresses context overload by dividing complex designs
    # into focused sub-tasks with limited context per agent.
    #
    # Architecture:
    #   DesignSupervisor (orchestrator)
    #     └── ModuleAgent (per module)
    #           ├── ComponentAgent (component selection)
    #           ├── ConnectionAgent (connection synthesis)
    #           └── ValidationAgent (per-module ERC)
    #     └── IntegrationAgent (cross-module connections)
    # =========================================================================
    MULTI_AGENT_CONFIG = {
        # Enable/disable multi-agent mode
        # When disabled, falls back to single-agent two-stage approach
        "enabled": True,

        # Maximum parallel module agents
        # Higher = faster but more API load
        # Recommended: 2-3 for API rate limits
        "max_parallel_modules": 2,

        # Retry configuration per agent
        "max_retries_per_agent": 2,
        "retry_delay_seconds": 10,

        # Validation thresholds
        "max_validation_iterations": 5,

        # Allow imperfect modules to continue
        # If False, any validation failure stops the process
        # If True, logs warnings and continues
        "allow_imperfect_modules": True,

        # Component limits per module
        # If module exceeds this, consider splitting
        "max_components_per_module": 60,
        "warn_components_per_module": 40,

        # Enable parallel module design
        # If False, modules are designed sequentially
        "enable_parallel_design": True,

        # Enable backplane generation
        # Creates bulk capacitors, test points for inter-module
        "enable_backplane": True,

        # Debug settings
        "log_agent_prompts": False,  # Log full prompts (verbose!)
        "save_intermediate_results": True,  # Save each agent's output
    }

    # =========================================================================
    # QUALITY GATE CONFIGURATION (February 2026 — Forensic Fix Plan)
    # =========================================================================
    # Single source of truth for all pipeline quality thresholds.
    # These values are referenced by Step 3, Circuit Fixer, Rating Validator,
    # Design Supervisor, QA, and the workflow orchestrator.
    #
    # Override any value via the corresponding environment variable.
    # =========================================================================
    QUALITY_GATES = {
        # --- Step 3: Fallback module ratio enforcement ---
        # Minimum fraction of modules that must be AI-designed (not fallback)
        # for the workflow to report success. Range: 0.0 – 1.0
        "min_successful_module_ratio": float(
            os.getenv("MIN_SUCCESSFUL_MODULE_RATIO", "0.5")
        ),

        # --- Design Supervisor: Multi-agent success threshold ---
        # Minimum fraction of modules the supervisor must design successfully
        # before proceeding to integration. Range: 0.0 – 1.0
        "min_multi_agent_success_ratio": float(
            os.getenv("MIN_MULTI_AGENT_SUCCESS_RATIO", "0.8")
        ),

        # --- QA: Semantic quality minimums ---
        # Minimum number of components expected per real module.
        # A fallback circuit has only 2; any real module should exceed this.
        "min_components_per_module": int(
            os.getenv("MIN_COMPONENTS_PER_MODULE", "5")
        ),

        # --- API pre-flight health check ---
        # Maximum tokens used for the lightweight health-check ping.
        "preflight_max_tokens": int(
            os.getenv("PREFLIGHT_MAX_TOKENS", "10")
        ),

        # Timeout (seconds) for the pre-flight health check.
        "preflight_timeout": float(
            os.getenv("PREFLIGHT_TIMEOUT", "15")
        ),

        # --- Phase C: Circuit Fixer hard gate ---
        # Maximum number of critical fixer issues allowed for a circuit to
        # be considered successful. 0 = no critical issues tolerated.
        "max_critical_fixer_issues": int(
            os.getenv("MAX_CRITICAL_FIXER_ISSUES", "0")
        ),

        # --- Phase A: Integration signal matching ---
        # Minimum fraction of interface signals that must be connected
        # for integration to be considered successful. Range: 0.0 – 1.0
        "min_interface_connection_ratio": float(
            os.getenv("MIN_INTERFACE_CONNECTION_RATIO", "0.5")
        ),

        # --- Phase A: Signal matching minimum lengths ---
        # Minimum character length for Strategy 3 (suffix match)
        "integration_min_suffix_len": int(
            os.getenv("INTEGRATION_MIN_SUFFIX_LEN", "4")
        ),
        # Minimum character length for Strategy 4 (contains match)
        # H.11: Raised from 5→6 to prevent false positives (e.g., "POWER",
        # "CLOCK" matching unrelated nets like "BLOCK_CTRL").
        "integration_min_contains_len": int(
            os.getenv("INTEGRATION_MIN_CONTAINS_LEN", "6")
        ),

        # --- Circuit Supervisor convergence ---
        # Maximum iterations with no improvement before early exit.
        "max_stall_iterations": int(
            os.getenv("MAX_STALL_ITERATIONS", "3")
        ),
        # Maximum total supervisor loop iterations.
        "max_supervisor_iterations": int(
            os.getenv("MAX_SUPERVISOR_ITERATIONS", "10")
        ),
        # Maximum circuit fixer iterations per module.
        "max_fixer_iterations": int(
            os.getenv("MAX_FIXER_ITERATIONS", "3")
        ),

        # --- Component rating validation ---
        # Voltage derating safety factor (e.g. 1.2 = 20% margin).
        "voltage_derating_factor": float(
            os.getenv("VOLTAGE_DERATING_FACTOR", "1.2")
        ),

        # --- Ground coverage validation ---
        # Minimum fraction of total connections that must be ground.
        "min_ground_connection_ratio": float(
            os.getenv("MIN_GROUND_CONNECTION_RATIO", "0.05")
        ),
    }

    # =========================================================================
    # API ERROR CLASSIFICATION (February 2026 — Forensic Fix Plan)
    # =========================================================================
    # Maps recognisable substrings in Anthropic error messages to categories.
    # The workflow uses these categories to decide retry vs. fail-fast.
    # Order matters: first match wins.
    # =========================================================================
    API_ERROR_CATEGORIES = {
        # category_key: list of substrings that indicate this category
        "CREDIT_EXHAUSTED": [
            "credit balance is too low",
            "insufficient_quota",
            "billing",
        ],
        "AUTH_FAILED": [
            "authentication_error",
            "invalid x-api-key",
            "permission_error",
            "unauthorized",
        ],
        "RATE_LIMITED": [
            "rate_limit",
            "too many requests",
            "429",
        ],
        "OVERLOADED": [
            "overloaded_error",
            "capacity",
        ],
        "SERVER_ERROR": [
            "internal_server_error",
            "500",
            "502",
            "503",
            "504",
        ],
    }

    # =========================================================================
    # SPICE GROUND PATTERNS (Phase E — Forensic Fix 20260208)
    # =========================================================================
    # Used by scripts/spice/netlist_generator.py to identify ground nets.
    # Structured as exact matches, prefixes, and suffixes to prevent false
    # positives like '0' matching any net containing the digit 0.
    # =========================================================================
    SPICE_GROUND_PATTERNS = {
        "exact": {"GND", "GROUND", "VSS", "0", "0V", "DGND", "AGND", "PGND", "SGND", "CGND"},
        "prefixes": ["GND_", "GROUND_"],
        "suffixes": ["_GND", "_GROUND", "_VSS"],
    }

    # =========================================================================
    # INTEGRATION GLOBAL NET PATTERNS (Phase A — Forensic Fix 20260208)
    # =========================================================================
    # Keywords that identify interface signals as global (cross-module) nets.
    # Matching uses prefix/suffix only (NOT substring) to prevent false positives.
    # Power rails, ground, and SYS_ prefix are always global regardless.
    # =========================================================================
    INTEGRATION_GLOBAL_NET_KEYWORDS = [
        "SENSE", "CONTROL", "SIGNAL", "OUTPUT", "INPUT",
        "DISPLAY", "LED", "SWITCH", "BUTTON",
        "PWM", "DAC", "ADC",
        "SHUTDOWN", "EMERGENCY", "STATUS",
        "FAN_CONTROL", "CHANNEL",
        # M.4 FIX: Power management, DDS, bias, and monitoring signals
        "PGOOD", "UVLO", "OVP", "OCP", "OTP",
        "READY", "VALID", "DETECTED", "ALARM",
        "DDS", "BIAS", "MONITOR", "TEMP",
    ]

    # M.4 FIX: Signal suffixes that indicate global (cross-module) signals.
    # Any net ending with these suffixes is treated as global by the
    # integration agent, regardless of other keyword matching.
    INTEGRATION_SIGNAL_SUFFIXES = [
        '_CONDITIONED', '_FILTERED', '_BUFFERED', '_DEBOUNCED',
        '_LATCHED', '_LEVEL', '_DELAYED',
    ]

    # Nets matching these patterns are NEVER globalised (stay module-local).
    INTEGRATION_LOCAL_NET_PATTERNS = ["NC_", "_LOCAL"]

    # =========================================================================
    # V.3 FIX: HARDWARE PREFIX STRIPPING FOR SEMANTIC MATCHING
    # =========================================================================
    # MCU-specific prefixes that the AI adds to signal names but that obscure
    # the functional meaning. These are stripped during semantic matching to
    # bridge the gap between hardware-specific names (ADC1_AIN0) and
    # functional interface names (I_SENSE_A).
    # =========================================================================
    INTEGRATION_HARDWARE_PREFIXES_TO_STRIP = [
        r'^ADC\d+_',       # ADC1_AIN0 -> AIN0
        r'^DAC\d+_',       # DAC1_OUT -> OUT
        r'^TIM\d+_',       # TIM1_CH1 -> CH1
        r'^HRTIM\d*_',     # HRTIM1_CHA1 -> CHA1 (high-resolution timer)
        r'^LPTIM\d*_',     # LPTIM1_OUT -> OUT (low-power timer)
        r'^P[A-K]\d+_?',   # PA0, PB12 -> (stripped to empty, handled)
        r'^GPIO\d*_?',     # GPIO12_ -> (stripped)
        r'^COMP\d+_',      # COMP1_OUT -> OUT
        r'^OPAMP\d+_',     # OPAMP2_OUT -> OUT
        r'^USART\d+_',     # USART1_TX -> TX
        r'^SPI\d+_',       # SPI2_MOSI -> MOSI
        r'^I2C\d+_',       # I2C1_SCL -> SCL
        r'^UART\d+_',      # UART3_RX -> RX
        r'^CAN\d+_',       # CAN1_TX -> TX
        r'^DMA\d+_',       # DMA1_CH3 -> CH3 (DMA channel)
        r'^SAI\d*_',       # SAI1_SD -> SD (serial audio interface)
        r'^SDMMC\d*_',     # SDMMC1_D0 -> D0 (SD/MMC interface)
    ]

    # V.3 FIX: Functional keyword mapping — maps common signal function
    # keywords to their typical interface contract names. Used when
    # hardware-stripped names still don't match.
    INTEGRATION_FUNCTIONAL_KEYWORDS = {
        'AIN': ['SENSE', 'ANALOG', 'ADC', 'INPUT', 'MEASURE'],
        'AOUT': ['DAC', 'ANALOG_OUT', 'OUTPUT'],
        'PWM': ['DRIVE', 'CONTROL', 'GATE', 'CMD'],
        'FAULT': ['ERROR', 'FAIL', 'ALARM', 'TRIP'],
        'ENABLE': ['EN', 'ON', 'ACTIVATE', 'START'],
        'SENSE': ['MEASURE', 'MONITOR', 'DETECT', 'AIN', 'ADC'],
        'TEMP': ['THERMAL', 'NTC', 'TEMPERATURE'],
        'GOOD': ['OK', 'READY', 'VALID', 'PGOOD'],
    }

    # Power net keywords — substring matching against net names (uppercase).
    # Used by integration agent to classify nets as global power.
    INTEGRATION_POWER_NET_KEYWORDS = [
        'VCC', 'VDD', 'V+', 'PWR', 'POWER',
        '5V', '12V', '3V3', '3V', '24V', '15V', '180V',
        '+5V', '+12V', '+3V3', '+24V', '+15V', '+180V', '-15V', '-180V',
        'DC_', '_DC', 'AC_', '_AC',
    ]

    # Ground net keywords — substring matching against net names (uppercase).
    # Used by integration agent to classify nets as global ground.
    INTEGRATION_GROUND_NET_KEYWORDS = [
        'GND', 'VSS', 'V-', 'GROUND', '0V', 'PGND', 'AGND', 'DGND',
    ]

    # System bus signal keywords — substring matching against net names (uppercase).
    # Used by integration agent to classify nets as global bus signals.
    INTEGRATION_SYSTEM_NET_KEYWORDS = [
        'CLK', 'CLOCK', 'RESET', 'ENABLE', 'FAULT',
        'SPI', 'I2C', 'UART', 'USB', 'CAN',
        'MOSI', 'MISO', 'SCK', 'SDA', 'SCL', 'TX', 'RX',
        # M.4 FIX: Power management and DDS signals commonly cross modules
        'PGOOD', 'UVLO', 'OVP', 'OCP', 'DDS',
    ]

    # Regex pattern for pin-reference net names that must be rejected.
    # Matches patterns like "U2.6", "R10.2", "Q1.3" — these are pin references,
    # NOT signal names.
    PIN_REFERENCE_PATTERN = r'^[A-Z]+\d+\.\d+$'

    # Pre-compiled version — import this instead of re-compiling everywhere.
    import re as _re
    PIN_REFERENCE_PATTERN_RE = _re.compile(PIN_REFERENCE_PATTERN)

    # =========================================================================
    # SYS_ NET INTEGRATION (February 2026 — Fix H.1/H.2)
    # =========================================================================
    # Prefix used for global cross-module interface signals.
    # The Integration Agent creates "SYS_<signal>" nets to connect modules.
    # =========================================================================
    SYS_NET_PREFIX = os.getenv("SYS_NET_PREFIX", "SYS_")

    # =========================================================================
    # CONNECTION AGENT POWER/GROUND DETECTION (February 2026 — Fix H.6)
    # =========================================================================
    # Keywords used to auto-detect power pins when the AI omits connections.
    # These are checked against pin NAMES (uppercase), not net names.
    # Separate from INTEGRATION_POWER_NET_KEYWORDS which match net names.
    # =========================================================================
    POWER_PIN_KEYWORDS = frozenset({
        'VCC', 'VDD', 'V+', 'VIN', 'VBUS', 'VBAT', 'VSYS',
        'AVCC', 'AVDD', 'DVCC', 'DVDD', 'PVCC', 'PVDD',
        'VCC_IO', 'VDDIO', 'VDDQ',
    })

    GROUND_PIN_KEYWORDS = frozenset({
        'GND', 'VSS', 'V-', 'AGND', 'DGND', 'PGND', 'SGND',
        'AVSS', 'DVSS', 'COM', 'COMMON', 'EP', 'EPAD',
        'VEE', 'PAD', 'EXPOSED_PAD',
    })

    # =========================================================================
    # FILENAME / MODULE NAMING DEFAULTS (February 2026 — Fix H.9)
    # =========================================================================
    # Sanitisation for output filenames and default fallback names.
    # =========================================================================
    MAX_FILENAME_LENGTH = int(os.getenv("MAX_FILENAME_LENGTH", "40"))
    FILENAME_SANITIZE_PATTERN = r'[()[\]{}]'  # chars stripped from filenames
    DEFAULT_FALLBACK_MODULE_NAME = "Main_Circuit"

    # =========================================================================
    # ISSUE SEVERITY CLASSIFICATION (February 2026 — Fix H.8)
    # =========================================================================
    # Tags each ERC issue type with a severity level so the supervisor can
    # early-exit on unrecoverable CRITICAL issues and skip INFO-level ones.
    # =========================================================================
    ISSUE_SEVERITY = {
        # CRITICAL — circuit will NOT function; no automated fix possible
        "shorted_passives": "CRITICAL",
        "phantom_component": "CRITICAL",
        "missing_components": "CRITICAL",
        "missing_pinNetMapping": "CRITICAL",

        # HIGH — circuit likely broken but fixer may resolve
        "power_connections": "HIGH",
        "invalid_pin": "HIGH",
        "wrong_connection_format": "HIGH",

        # MEDIUM — design quality issue, not a hard failure
        "floating_components": "MEDIUM",
        "pin_mismatches": "MEDIUM",
        "net_conflicts": "MEDIUM",
        "insufficient_connection_points": "MEDIUM",

        # LOW — informational, no fix required
        "single_ended_nets": "LOW",
        "missing_connections": "LOW",
    }

    # =========================================================================
    # POWER RAIL DETECTION (February 2026 — Fix III.1)
    # =========================================================================
    # Single source of truth for power rail identification.  Used by:
    #   workflow/circuit_supervisor.py  _is_power_rail()
    #   scripts/spice/netlist_generator.py  _is_power_rail_local()
    # All patterns operate on UPPERCASE net names.
    # =========================================================================
    POWER_RAIL_PREFIXES = [
        'VCC', 'VDD', 'VSS', 'VEE', 'VBAT', 'VIN', 'VOUT',
        'VBUS', 'VPOS', 'VNEG',
    ]

    POWER_RAIL_EXACT = frozenset({'V+', 'V-'})

    POWER_RAIL_PATTERNS = [
        r'^V\d+',               # V12, V5, V3, V12_OUT, V5_NEG, V3P3
        r'^\d+V',               # 12V, 5V, 3V, 24VDC, 48VDC
        r'^[+-]\d+',            # +5V, +12VDC_rail, -15V, +24V
        r'^PWR',                # PWR, PWR_MAIN, PWR_INPUT
        r'V(POS|NEG)',          # VPOS, VNEG (anywhere in name)
        r'^V_(POS|NEG)',        # V_POS_12V, V_NEG_12V
        r'^V_\d+',              # V_12, V_5
        r'^VREF',               # VREF_5V, VREF_2V5
        r'^VB[_A-Z]',           # VB_A, VB_HIGH (bootstrap pins)
        r'^HV_',                # HV_DC_BULK, HV_RAIL
        r'^LV_',                # LV_RAIL, LV_DC
        r'_BULK$',              # HV_DC_BULK
        r'PROTECTED$',          # VIN_PROTECTED
        r'FUSED$',              # VIN_FUSED
        # M.5 FIX: Additional power rail patterns
        r'VBUS',                # USB_VBUS, VBUS_5V
        r'.*_FILT$',            # USB_VBUS_FILT, VCC_FILT
        r'.*_REG$',             # VCC_REG, VDD_3V3_REG
        r'VIN_RAW',             # VIN_RAW_10-15V (external input)
        # Q.1 FIX: Generic power name variants missed by existing patterns
        r'^POWER[_]?\d*',          # POWER, POWER_5V, POWER_3V3, POWER5V
        r'.*_VCC$',                # ANALOG_VCC, DIGITAL_VCC, CORE_VCC
        r'.*_VDD$',                # ANALOG_VDD, DIGITAL_VDD, CORE_VDD
        r'.*_VEE$',                # ANALOG_VEE, DIGITAL_VEE
        r'.*_VSS$',                # ANALOG_VSS, DIGITAL_VSS
        r'V_?SUP',                 # VSUP, V_SUPPLY, VSUPPLY
        # Y.1 FIX: RAIL_ and SUPPLY_ prefixed nets (RAIL_5V, SUPPLY_3V3)
        r'^RAIL_',                     # RAIL_5V, RAIL_12V, RAIL_3V3
        r'^SUPPLY_',                   # SUPPLY_5V, SUPPLY_12V
        # Y.1 FIX: Signed rail variants (common in multi-domain PSUs)
        r'^[+-]?\d+V\d*_',            # +5V_, -15V_, 12V_ (rail prefix with suffix)
    ]

    # M.5 FIX: Nets matching these patterns are exempt from single-ended
    # checks — they represent external connections that are inherently
    # single-ended within a module (connected externally).
    SINGLE_ENDED_EXEMPT_PATTERNS = [
        r'VIN_RAW',             # External voltage input
        r'VIN_EXT',             # External voltage input
        r'VBUS',                # USB bus power
        r'_INPUT$',             # External input suffix
        r'_EXT$',               # External connection suffix
        # N.2 FIX: Short UART modem signal names (too short for substring matching)
        r'^RI$',                # Ring Indicator (exact match to avoid PRIMARY/DRIVE)
        # X.3 FIX: Hardware instance-prefixed peripheral signals (ADC1_AIN0,
        # SPI2_MOSI, UART3_TX, TIM4_CH1, I2C2_SDA, COMP1_OUT, USART1_RX).
        # The digit after the peripheral type prevents matching by plain
        # substring (e.g., ADC_ matches ADC_IN but not ADC1_AIN0).
        r'^(?:ADC|DAC|COMP|TIM|SPI|I2C|UART|USART|SAI|SDMMC|QSPI|FDCAN)\d+_',
        # X.3 FIX: Pin-reference net names — nets named after component pins
        # (NET_F1_1, NET_U1_PIN2, NET_Q3_GATE). These are legitimate
        # cross-module interfaces created by the integration agent.
        r'^NET_[A-Z]+\d+_',
    ]

    # =========================================================================
    # SPICE POWER SOURCE AUTO-GENERATION (February 2026 — Fix I.1)
    # =========================================================================
    # Patterns used by the SPICE netlist generator to auto-create voltage
    # sources for detected power rails.  Each entry is (regex, default_volts):
    #   - If default_volts is None, the voltage is extracted from the regex
    #     capture groups (e.g. VCC_5V → 5).
    #   - If default_volts is a float, that value is used when the net name
    #     matches but no voltage can be extracted (e.g. VCC → 5.0).
    # Patterns are matched against UPPERCASE net names.
    # =========================================================================
    SPICE_POWER_SOURCE_PATTERNS = [
        # Fix K.5: Two-capture-group patterns FIRST to correctly parse xVy notation
        # (e.g. VCC_3V3 → 3.3, VDD_1V8 → 1.8). The single-group pattern
        # r'V(?:CC|DD)_?(\d+)V?' would capture only "3" from VCC_3V3 → wrong 3.0V.
        (r'V(?:CC|DD)_?(\d+)V(\d+)', None),   # VCC_3V3 → 3.3, VDD_1V8 → 1.8
        (r'V(?:CC|DD)_?(\d+)V?$', None),      # VCC_5V → 5, VDD_12V → 12 (no fractional)
        # Fix L.3: xVy with optional suffix (3V3_DIGITAL → 3.3, 1V8_ANALOG → 1.8)
        (r'(\d+)V(\d+)(?:_\w+)?$', None),     # 3V3, 3V3_DIGITAL, 1V8_ANALOG
        (r'V_?(\d+)V(\d+)(?:_\w+)?$', None),  # V_3V3, V_3V3_REG
        (r'V_?(\d+)V?$', None),                # V_5V → 5, V_12 → 12
        # Fix L.3: Bare voltage with optional suffix (12V_DIGITAL → 12, 180V_DC → 180)
        (r'(\d+)V(?:_\w+)?$', None),           # 12V, 12V_DIGITAL, 180V_DC, 5V_ANALOG
        (r'V_?PLUS_?(\d+)V?', None),           # V_PLUS_15V → +15V
        (r'V_?MINUS_?(\d+)V?', None),          # V_MINUS_15V → -15V
        (r'V_?NEG_?(\d+)V?', None),            # V_NEG_18V → -18V
        # Fix L.3: HV/LV prefix patterns (HV_DC_BULK → try to extract voltage)
        (r'HV_?(\d+)V?', None),                # HV_360V → 360, HV_180V_DC → 180
        (r'LV_?(\d+)V?', None),                # LV_12V → 12, LV_5V_RAIL → 5
        (r'VCC$', 5.0),                        # VCC → 5V default
        (r'VDD$', 3.3),                        # VDD → 3.3V default
        (r'V5V?$', 5.0),                       # V5, V5V → 5V
        (r'V12V?$', 12.0),                     # V12, V12V → 12V
        (r'V24V?$', 24.0),                     # V24, V24V → 24V
        (r'V48V?$', 48.0),                     # V48, V48V → 48V
        (r'V3V3$', 3.3),                       # V3V3 → 3.3V (fallback)
        (r'V1V8$', 1.8),                       # V1V8 → 1.8V (fallback)
        (r'V2V5$', 2.5),                       # V2V5 → 2.5V
        # Q.7 FIX: POWER_xV variants (POWER_5V → 5, POWER_3V3 → 3.3)
        (r'POWER_?(\d+)V(\d+)', None),         # POWER_3V3 → 3.3, POWER_1V8 → 1.8
        (r'POWER_?(\d+)V?$', None),            # POWER_5V → 5, POWER_12V → 12
        # Q.7 FIX: Suffixed VCC/VDD variants (ANALOG_VCC → default voltages)
        (r'.*_VCC$', 5.0),                     # ANALOG_VCC, DIGITAL_VCC → 5V default
        (r'.*_VDD$', 3.3),                     # ANALOG_VDD, DIGITAL_VDD → 3.3V default
        # T.3 FIX: Compound net name patterns (VOUT_5V, VIN_12V, etc.)
        (r'VOUT_?(\d+)V(\d+)', None),         # VOUT_3V3 → 3.3, VOUT_1V8 → 1.8
        (r'VOUT_?(\d+)V?$', None),            # VOUT_5V → 5, VOUT_12V → 12
        (r'VIN_?(\d+)V(\d+)', None),          # VIN_3V3 → 3.3
        (r'VIN_?(\d+)V?$', None),             # VIN_5V → 5, VIN_12V → 12
        (r'.*_(\d+)V(\d+)$', None),           # SYS_VIN_3V3 → 3.3 (generic suffix)
        (r'.*_(\d+)V$', None),                # SYS_VIN_5V → 5 (generic suffix)
    ]

    # Q.8 FIX: Subcircuit output pin names whose connected nets must NOT
    # get auto-generated voltage sources (prevents voltage source loops in
    # SPICE simulation — two ideal sources on the same node = singular matrix).
    SPICE_SUBCIRCUIT_OUTPUT_PIN_NAMES = frozenset({
        'OUT', 'VOUT', 'SW', 'HO', 'LO',       # Output driver pins
        'IOUT', 'IOUTB',                          # Current output pins
        'OUT_A', 'OUT_B', 'OUTPUT',               # Generic output names
        'OUTA', 'OUTB',                            # Dual output variants
        'DAC_OUT', 'ADC_OUT',                      # DAC/ADC output pins
    })

    # =========================================================================
    # CIRCUIT SUPERVISOR FALSE POSITIVE FILTERS (February 2026 — Fix G.4)
    # =========================================================================
    # These patterns reduce the circuit supervisor's 70% false positive rate
    # by classifying expected single-ended nets and valid ground variants.
    # All patterns are GENERIC — they work for any circuit type.
    # =========================================================================

    # Net name patterns that are EXPECTED to be single-ended (not flagged).
    # MCU GPIO patterns: PA0_GPIO, PB12_ADC, PE5_GPIO, etc.
    # Also includes bare MCU port pins (PA0, PB5, PC13).
    SUPERVISOR_GPIO_PATTERNS = [
        r'^P[A-K]\d+_GPIO$',
        r'^P[A-K]\d+_ADC$',
        r'^P[A-K]\d+_DAC$',
        r'^P[A-K]\d+_TIM$',
        r'^P[A-K]\d+_AF\d+$',
        r'^GPIO\d+$',
        r'^IO\d+$',
        r'^P[A-K]\d+$',         # Bare MCU port pins (PA0, PB5, PC13)
    ]

    # Extended ground pin names recognized as valid ground connections.
    # Dual-supply ICs use AGND/PGND/COM; some only have V-/VEE with no GND pin.
    # Y.1 FIX: Added COMM (symmetric with COM — many Analog Devices ICs use COMM)
    SUPERVISOR_GROUND_PIN_NAMES = frozenset({
        'GND', 'VSS', 'V-', 'AGND', 'DGND', 'PGND', 'SGND',
        'AVSS', 'DVSS', 'EP', 'EPAD', 'COM', 'COMM', 'COMMON',
        'VEE', 'GNDA', 'GNDD', 'PAD', 'EXPOSED_PAD',
    })

    # =========================================================================
    # Y.1 FIX: SUPERVISOR POWER PIN NAMES (single source of truth)
    # =========================================================================
    # Migrated from hardcoded frozenset in circuit_supervisor.py to config.
    # Pin names (uppercase) that indicate a power supply connection on an IC.
    # Used by circuit_supervisor._check_power_connections() to detect
    # whether an IC has power pins connected to valid rails.
    # GENERIC: covers standard, analog, digital, domain-specific, and
    # manufacturer-specific power pin naming conventions.
    # =========================================================================
    SUPERVISOR_POWER_PIN_NAMES = frozenset({
        # Standard power names
        'VCC', 'VDD', 'V+', 'VIN', 'VSUPPLY', 'VS', 'VPWR',
        # Analog/digital domain-specific
        'AVCC', 'DVCC', 'AVDD', 'DVDD', 'PVCC', 'PVDD',
        'VCCA', 'VCCD', 'VDDA', 'VDDD', 'VCC_A', 'VCC_D', 'VDD_A', 'VDD_D',
        # IO and peripheral domains
        'VCC_IO', 'VDDIO', 'VDDQ',
        # Battery and system
        'VBAT', 'VSYS', 'V_SUPPLY',
        # Input-side power variants
        'VCC_IN', 'VDD_IN', 'AVDD_IN', 'DVDD_IN',
        # Positive/negative supply (analog ICs — AD8302, AD633, etc.)
        'VPOS', 'VNEG', 'VS+', 'VS-', 'V_POS', 'V_NEG',
        # Generic
        'POWER', 'PWR', 'VPP',
    })

    # Extended ground net names recognized as valid ground connections.
    # These are net names (not pin names) checked against pinNetMapping values.
    SUPERVISOR_GROUND_NETS = frozenset({
        'GND', 'AGND', 'DGND', 'PGND', 'SGND', 'CGND',
        'VSS', 'VEE', 'GROUND', 'EARTH', 'CHASSIS',
        'HV_GND', 'LV_GND', 'PWR_GND', 'GND_ISO', 'ISO_GND',
        'GND_ISOLATED', 'GND_RTN', 'RTN', 'RETURN',
        '0V', 'COM', 'COMMON',
    })

    # Pin names that indicate the IC's negative supply (acts as ground ref).
    # An IC with V- or VEE connected to a negative rail does NOT need GND.
    SUPERVISOR_NEGATIVE_SUPPLY_PIN_NAMES = frozenset({
        'V-', 'VEE', 'VSS', 'V_NEG', 'VNEG',
    })

    # =========================================================================
    # V.6 FIX: ISOLATION DOMAIN GROUND PATTERNS
    # =========================================================================
    # Net name patterns that represent intentional isolated ground references
    # in power electronics. When a ground-like pin (VSSA, VSS, PGND) is
    # connected to one of these nets, it is NOT a pin mismatch — it's a valid
    # isolated ground domain (e.g., H-bridge midpoint, isolated gate driver).
    # =========================================================================
    ISOLATION_GROUND_PATTERNS = [
        r'(?i)ISO_GND',           # Isolated ground
        r'(?i)GND_ISO',           # Isolated ground (alternate naming)
        r'(?i)BRIDGE_MID',        # H-bridge midpoint (center-tap ground)
        r'(?i)HS_GND',            # High-side ground reference
        r'(?i)HS_SOURCE',         # High-side MOSFET source (floating ground)
        r'(?i)FLOAT_GND',         # Floating ground domain
        r'(?i)SEC_GND',           # Secondary-side isolated ground
        r'(?i)PRI_GND',           # Primary-side isolated ground
        r'(?i)COM_[A-Z]',         # Domain-specific common (COM_A, COM_B)
        r'(?i)V(?:SS|EE)_[A-Z]', # Domain-specific grounds (VSS_A, VEE_B)
        r'(?i)GND_[A-Z]$',       # Domain-suffixed ground (GND_A, GND_B)
        r'(?i)MID(?:POINT)?',     # Generic midpoint nodes
        r'(?i)CENTER_TAP',        # Transformer center tap
    ]

    # =========================================================================
    # COMPONENT TAXONOMY (February 2026 — Professional Upgrade)
    # =========================================================================
    # Hierarchical classification of components for semantic analysis.
    # Used by CircuitSupervisor to determine power/ground requirements
    # and by the SPICE converter for model selection.
    # =========================================================================
    SEMANTIC_TAXONOMY = {
        "ACTIVE_IC": {
            "mcu": ["microcontroller", "mcu", "fpga", "cpld", "processor", "dsp"],
            "analog": ["opamp", "amplifier", "comparator", "buffer", "instrumentation_amp"],
            "power": ["regulator", "ldo", "switching_regulator", "buck", "boost", "pmic", "charge_pump"],
            "driver": ["gate_driver", "motor_driver", "led_driver", "display_driver", "mosfet_driver"],
            "data": ["adc", "dac", "codec", "dds", "synthesizer", "pll", "oscillator_ic"],
            "interface": ["transceiver", "phy", "can_transceiver", "uart_bridge", "usb_bridge", "level_shifter"],
            "logic": ["logic", "gate", "flipflop", "multiplexer", "mux", "demux", "shift_register"],
            "memory": ["memory", "eeprom", "flash", "sram", "sdram", "nvram"],
            "sensor": ["sensor", "temp_sensor", "accel", "gyro", "mag", "pressure_sensor"]
        },
        "PASSIVE": [
            "resistor", "capacitor", "inductor", "ferrite", "bead", "ferrite_bead", "fuse", "varistor",
            # M.9 FIX: Passive sensor types — these are 2-terminal resistance devices,
            # NOT active ICs. Without this, they trigger false "missing VCC/GND" errors.
            "ntc", "thermistor", "ptc", "rtd", "photodiode", "photoresistor", "ldr",
            # M.6: NTC/PTC variants
            "ntc_thermistor", "temperature_sensor", "temp_sensor",
        ],
        "SEMICONDUCTOR": ["diode", "led", "zener", "mosfet", "bjt", "igbt", "triac", "scr", "jfet"],
        "INTERCONNECT": ["connector", "header", "terminal", "jumper", "testpoint", "test_point"],
        "ELECTROMECHANICAL": ["switch", "relay", "buzzer", "motor", "solenoid", "speaker", "piezo",
                              "meter", "panel_meter", "ammeter", "voltmeter"],
        "MECHANICAL": ["heatsink", "mounting", "fiducial", "shield", "enclosure", "fan"]
    }

    # Fix K.1: Categories whose members do NOT require VCC+GND power connections.
    # Used by circuit_supervisor._is_active_device() to exclude false positives.
    # Dynamically built from SEMANTIC_TAXONOMY so adding a new category or type
    # in one place automatically propagates everywhere.
    NON_ACTIVE_TAXONOMY_CATEGORIES = (
        "PASSIVE", "INTERCONNECT", "SEMICONDUCTOR", "ELECTROMECHANICAL", "MECHANICAL"
    )

    # Flat set of all types that REQUIRE power/ground connections.
    # Dynamically generated from ACTIVE_IC taxonomy to avoid duplication.
    ACTIVE_COMPONENT_TYPES = frozenset([
        item for sublist in SEMANTIC_TAXONOMY["ACTIVE_IC"].values() for item in sublist
    ]) | {"ic"}

    # Fix K.1: Flat set of all types that do NOT require power/ground.
    # Built dynamically from NON_ACTIVE_TAXONOMY_CATEGORIES.
    _non_active_items: set = set()
    for _cat in NON_ACTIVE_TAXONOMY_CATEGORIES:
        _entries = SEMANTIC_TAXONOMY.get(_cat, [])
        if isinstance(_entries, list):
            _non_active_items.update(_entries)
        elif isinstance(_entries, dict):
            for _sub_list in _entries.values():
                _non_active_items.update(_sub_list)
    NON_ACTIVE_COMPONENT_TYPES = frozenset(_non_active_items)
    del _non_active_items, _cat, _entries  # cleanup class-scope temporaries

    # =========================================================================
    # CENTRALIZED COMPONENT TYPE SETS (February 2026 — R-series audit)
    # Single source of truth for component type classification used across
    # circuit_supervisor, circuit_fixer, and other validation modules.
    # =========================================================================

    # Two-terminal passive types that can be checked for shorted-pins (same-net).
    # Used by circuit_supervisor._check_shorted_passives().
    TWO_PIN_PASSIVE_TYPES = frozenset({
        'resistor', 'capacitor', 'inductor', 'diode', 'fuse', 'crystal',
        'led', 'ferrite', 'varistor', 'thermistor', 'ntc', 'ptc',
    })

    # Reference prefixes for two-pin passives (R1, C2, L3, D4, F1, Y1, etc.)
    TWO_PIN_PASSIVE_PREFIXES = frozenset({'R', 'C', 'L', 'D', 'F', 'Y'})

    # Component types that have voltage ratings requiring validation.
    VOLTAGE_RATED_TYPES = frozenset({
        'mosfet', 'nmos', 'pmos', 'fet', 'transistor', 'bjt', 'npn', 'pnp',
        'diode', 'zener', 'led', 'schottky', 'tvs',
        'capacitor', 'electrolytic',
        'ic', 'driver', 'gate_driver',
        'igbt', 'triac', 'scr',
    })

    # IC pin name keywords that indicate a floating input risk.
    FLOATING_INPUT_KEYWORDS = frozenset({
        'IN', 'INPUT', 'GATE', 'ENABLE', 'CLK', 'DATA', 'ADDR', 'RESET',
    })

    # Power signal classification patterns used by design_supervisor
    # to distinguish power from signal nets during interface definition.
    DESIGN_SUPERVISOR_POWER_SIGNAL_PATTERNS = (
        'V', 'VCC', 'VDD', 'GND', 'GROUND', 'VSS', 'RAIL', 'BUS',
        'POWER', 'SUPPLY', 'MAINS', 'AC_',
    )

    # =========================================================================
    # BEHAVIORAL MODEL PIN MAPS (February 2026 — Fix K.4)
    # =========================================================================
    # Canonical pin name lists for known IC behavioral models in SPICE.
    # Used to adapt AI-generated pin lists to behavioral model definitions.
    # Each key is the IC part name (uppercase). Value is a list of pin names
    # in the EXACT order the .subckt definition expects.
    # Adding an entry here automatically enables the behavioral model for that IC.
    # =========================================================================
    BEHAVIORAL_MODEL_PIN_MAP = {
        'OPAMP_GENERIC': ['INP', 'INN', 'VCC', 'VEE', 'OUT'],
        'LM358': ['INP', 'INN', 'VCC', 'VEE', 'OUT'],
        'AD9833': ['COMP', 'VDD', 'CAP', 'DGND', 'MCLK', 'AGND', 'VOUT', 'AVDD', 'SCLK', 'SDATA', 'FSYNC'],
        'IR2110': ['VCC', 'HIN', 'LIN', 'COM', 'LO', 'VSS', 'VB', 'HO'],
        'IR2113': ['VCC', 'HIN', 'LIN', 'COM', 'LO', 'VSS', 'VB', 'HO'],
        'TPS54331': ['BOOT', 'VIN', 'EN', 'SS', 'VSENSE', 'COMP', 'GND', 'SW'],
        'AD9851': ['DGND', 'AVDD', 'DVDD', 'AGND', 'VOUT', 'DAC_BP', 'IOUT', 'IOUTB', 'VINN', 'VINP'],
        'LM7805': ['IN', 'GND', 'OUT'],
        'LM7812': ['IN', 'GND', 'OUT'],
        'LM7815': ['IN', 'GND', 'OUT'],
        'LM7915': ['IN', 'GND', 'OUT'],
        'LM317': ['IN', 'ADJ', 'OUT'],
        'AMS1117': ['GND', 'IN', 'OUT'],
        # M.3 FIX: Voltage-suffixed variants (AI generates "AMS1117-3.3" etc.)
        'AMS1117-3.3': ['GND', 'IN', 'OUT'],
        'AMS1117-5.0': ['GND', 'IN', 'OUT'],
        'AMS1117-1.8': ['GND', 'IN', 'OUT'],
        'AMS1117-2.5': ['GND', 'IN', 'OUT'],
        'AMS1117-1.5': ['GND', 'IN', 'OUT'],
        'AMS1117-ADJ': ['GND', 'IN', 'OUT'],
    }

    # =========================================================================
    # SPICE PIN NAME ALIASES (February 2026 — Fix L.1)
    # =========================================================================
    # Maps common AI-generated pin name variants to canonical SPICE pin names.
    # Used by the SPICE netlist generator to reorder component pins from
    # AI-generated order to the SPICE-required order (D,G,S,B for MOSFET;
    # C,B,E for BJT; A,K for diode).
    #
    # Structure: { SpiceType: { canonical_name: [aliases...] } }
    # The canonical names MUST match the pin_order in ComponentModel.
    # Adding aliases here automatically enables recognition in all circuits.
    # =========================================================================
    SPICE_PIN_NAME_ALIASES = {
        'MOSFET': {
            # Canonical SPICE order: D, G, S, B (Drain, Gate, Source, Body)
            'D': [
                'DRAIN', 'DRN', 'D1', 'D2', 'D3',
                'TAB',  # Power MOSFETs often expose drain as tab
            ],
            'G': [
                'GATE', 'GT', 'G1', 'G2', 'G3',
                'INPUT',  # Some datasheets label gate as input
            ],
            'S': [
                'SOURCE', 'SRC', 'S1', 'S2', 'S3',
            ],
            'B': [
                'BODY', 'BULK', 'SUBSTRATE', 'SUB', 'B1',
                'BACKGATE',
            ],
        },
        'BJT': {
            # Canonical SPICE order: C, B, E (Collector, Base, Emitter)
            'C': [
                'COLLECTOR', 'COL', 'COLL', 'C1', 'C2',
            ],
            'B': [
                'BASE', 'BAS', 'B1', 'B2',
            ],
            'E': [
                'EMITTER', 'EMIT', 'EM', 'E1', 'E2',
            ],
        },
        'DIODE': {
            # Canonical SPICE order: A, K (Anode, Cathode)
            'A': [
                'ANODE', 'AN', 'A1', 'P', 'PLUS', '+',
            ],
            'K': [
                'CATHODE', 'CATH', 'CAT', 'K1', 'C', 'N', 'MINUS', '-',
            ],
        },
        'JFET': {
            # Canonical SPICE order: D, G, S (Drain, Gate, Source)
            'D': [
                'DRAIN', 'DRN',
            ],
            'G': [
                'GATE', 'GT',
            ],
            'S': [
                'SOURCE', 'SRC',
            ],
        },
    }

    # =========================================================================
    # FERRITE BEAD IDENTIFICATION (February 2026 — Fix K.13)
    # =========================================================================
    # Component types and reference designator prefixes that identify ferrite
    # beads. These must be modeled as series resistors (impedance at 100MHz),
    # NOT as inductors.
    # =========================================================================
    FERRITE_BEAD_TYPES = frozenset([
        'ferrite', 'ferrite_bead', 'bead', 'emi_filter',
    ])
    FERRITE_BEAD_REF_PREFIXES = ('FB', 'LFB', 'BLM', 'EMI')

    # =========================================================================
    # CONNECTOR TYPES FOR SPICE (February 2026 — Fix K.6)
    # =========================================================================
    # Component types that represent passive feedthrough connectors.
    # These should NOT be modeled as 0.001Ω resistors in SPICE — each pin
    # is an independent node with no internal connection to other pins.
    # =========================================================================
    # =========================================================================
    # NTC/PTC THERMISTOR IDENTIFICATION (February 2026 — Fix M.6)
    # =========================================================================
    # Component types and reference designator prefixes that identify NTC/PTC
    # thermistors. These are 2-terminal temperature-dependent resistors that
    # should be modeled as simple resistors at nominal resistance in SPICE.
    # =========================================================================
    NTC_THERMISTOR_TYPES = frozenset([
        'ntc', 'thermistor', 'ntc_thermistor', 'ptc',
        'temperature_sensor', 'temp_sensor', 'rtd',
    ])
    NTC_THERMISTOR_REF_PREFIXES = ('NTC', 'RT', 'TH')

    # =========================================================================
    # V.7 FIX: POTENTIOMETER / TRIMMER TYPES AND PREFIXES
    # =========================================================================
    # Potentiometers are 3-terminal variable resistors. In SPICE they are
    # modeled as a voltage divider at 50% wiper position (mid-range).
    # =========================================================================
    POTENTIOMETER_TYPES = frozenset([
        'potentiometer', 'trimmer', 'trimpot', 'pot',
        'variable_resistor', 'rheostat',
    ])
    POTENTIOMETER_REF_PREFIXES = ('RV', 'VR')

    # T.1 FIX: Type descriptor words that appear in component values but are
    # NOT part of the numeric value. Stripped before SPICE value parsing.
    # Generic — covers resistors, capacitors, inductors, thermistors, etc.
    SPICE_VALUE_TYPE_DESCRIPTORS = frozenset([
        # Thermistor types
        'ntc', 'ptc', 'thermistor',
        # Capacitor dielectrics
        'ceramic', 'electrolytic', 'tantalum', 'polymer', 'film',
        'polyester', 'polypropylene', 'mica', 'mylar',
        # Capacitor dielectric codes
        'x5r', 'x7r', 'x7s', 'y5v', 'cog', 'c0g', 'np0',
        # Resistor types
        'wirewound', 'carbon', 'metal', 'thick', 'thin',
        # Package/mounting
        'smd', 'tht', 'axial', 'radial', 'chip',
        # Generic descriptors
        'ferrite', 'precision', 'power',
    ])

    # T.3 FIX: Default voltage for power rails where voltage can't be
    # extracted from the net name (used in secondary detection pass).
    SPICE_DEFAULT_POWER_SOURCE_VOLTAGE = 5.0

    # =========================================================================
    # VOLTAGE EXTRACTION FROM NET NAMES (February 2026 — Fix M.7)
    # =========================================================================
    # Generic regex for extracting voltage values from net names.
    # Used by the rating validator to infer per-module voltage domain.
    # Matches: +12V, VCC_5V, 3V3, VDD_1V8, 48VDC, etc.
    # =========================================================================
    VOLTAGE_EXTRACTION_PATTERN = r'(\d+(?:\.\d+)?)\s*V'

    # M.7 FIX: xVy notation pattern (e.g., 3V3 → 3.3, 1V8 → 1.8)
    VOLTAGE_XVY_PATTERN = r'(\d+)V(\d+)'

    # M.11 FIX: Enable SPICE syntax pre-validation
    SPICE_VALIDATE_SYNTAX = True

    CONNECTOR_TYPES = frozenset([
        'connector', 'header', 'terminal', 'jack', 'plug', 'socket',
        'barrel_jack', 'usb_connector', 'rj45', 'rj11', 'bnc',
    ])

    # =========================================================================
    # V-SERIES STRUCTURAL DETECTION: REFERENCE DESIGNATOR PREFIXES
    # =========================================================================
    # Used for STRUCTURAL component detection (by type + by ref prefix).
    # The supervisor checks BOTH component type AND ref prefix to handle
    # circuits where type metadata may be missing or non-standard.
    # =========================================================================
    CONNECTOR_REF_PREFIXES = frozenset(['J', 'X', 'P', 'CN', 'CONN'])
    TESTPOINT_REF_PREFIXES = frozenset(['TP', 'TP_'])

    # =========================================================================
    # Y.6 FIX: CONFIGURATION PIN KEYWORDS (tie-to-rail exemption)
    # =========================================================================
    # Pin name keywords that indicate address/mode configuration pins.
    # When these pins are hard-tied to VCC or GND, it is a VALID hardware
    # configuration (e.g., I2C address selection, mode pin strapping).
    # The circuit supervisor suppresses pin_mismatch errors for these pins.
    # GENERIC: covers all IC families that use pin strapping for configuration.
    # =========================================================================
    CONFIG_PIN_KEYWORDS = frozenset({
        'ADDR', 'ADD', 'ADDRESS',       # I2C address pins
        'MODE', 'MOD',                   # Mode selection pins
        'SEL', 'SELECT',                 # Function/bus selection
        'CFG', 'CONFIG',                 # Configuration pins
        'SET', 'SETTING',                # Setting pins
        'BOOT', 'BOOT0', 'BOOT1',       # Boot mode pins (MCUs)
        'STRAP',                         # Generic strap pin
        'OPT', 'OPTION',                 # Option pins
        'PROG',                          # Programming/configuration
    })

    # Y.2 FIX: External input net patterns — nets that represent system-boundary
    # inputs from the outside world. These legitimately have no producer module
    # and should NOT be counted against the integration connection ratio.
    EXTERNAL_INPUT_NET_PATTERNS = [
        r'(?i)^VIN_RAW',                # Raw external voltage input
        r'(?i)^MAINS',                  # AC mains input
        r'(?i)^AC_IN',                  # AC input
        r'(?i)^DC_IN',                  # DC input
        r'(?i)^LINE_',                  # Power line
        r'(?i)^NEUTRAL_',              # Power neutral
        r'(?i)_EXT_IN$',               # External input suffix
        r'(?i)^EXT_',                  # External prefix
        r'(?i)^USB_VBUS$',            # USB bus power (from host)
        r'(?i)^BATT',                  # Battery input
    ]

    # =========================================================================
    # V-SERIES FIX: GENERIC MODULE PREFIX PATTERNS (replaces hardcoded regex)
    # =========================================================================
    # Regex patterns that identify module-prefixed interface nets.
    # These are nets created by the integration agent when prefixing module
    # signals (e.g., MOD1_SPI_MOSI, CH5_PWM, MODULE_A_OUTPUT).
    # Using config-driven patterns instead of hardcoded regex in code.
    # =========================================================================
    GENERIC_MODULE_PREFIX_PATTERNS = [
        r'^MOD\d+_',       # MOD1_, MOD2_
        r'^CH\d+_',        # CH1_, CH2_
        r'^MODULE\d*_',    # MODULE_, MODULE1_
        r'^CHANNEL\d*_',   # CHANNEL_, CHANNEL1_
        r'^STAGE\d*_',     # STAGE1_, STAGE2_
        r'^BANK\d*_',      # BANK1_, BANK2_
        r'^UNIT\d*_',      # UNIT1_, UNIT2_
        r'^SLOT\d*_',      # SLOT1_, SLOT2_
        r'^BOARD\d*_',     # BOARD1_, BOARD2_
        r'^CARD\d*_',      # CARD1_, CARD2_
    ]

    # =========================================================================
    # FEEDBACK DIVIDER VALIDATION (February 2026 — Fix K.10)
    # =========================================================================
    # Tolerance for feedback divider accuracy validation.
    # If calculated Vout deviates from specified Vout by more than this
    # fraction, the circuit supervisor flags it.
    # =========================================================================
    FEEDBACK_DIVIDER_TOLERANCE = float(os.getenv(
        "FEEDBACK_DIVIDER_TOLERANCE", "0.05"
    ))  # 5% default

    # Common feedback/sense pin names on regulators (generic, works with any IC)
    FEEDBACK_PIN_NAMES = frozenset([
        'FB', 'VSENSE', 'VSEN', 'VFB', 'FEEDBACK', 'ADJ', 'ADJUST',
        'SENSE', 'NFB', 'VOUT_SENSE',
    ])

    # =========================================================================
    # REFERENCE / SHUNT DEVICE KEYWORDS (February 2026 — Fix J.D)
    # =========================================================================
    # Keywords for detecting reference/shunt/regulator devices that do NOT
    # require a classical VCC pin (e.g. TL431, LM4040).
    # =========================================================================
    REFERENCE_SHUNT_DEVICE_KEYWORDS = [
        'TL431', 'TLV431',
        'LM4040', 'LM4041', 'REF30', 'REF31', 'REF32', 'REF33',
        'VREF', 'REFERENCE', 'SHUNT',
    ]

    # =========================================================================
    # POWER SUPPLY IC PATTERNS (February 2026 — Fix J.E)
    # =========================================================================
    # Pattern-based detection of power supply ICs that ARE the power source
    # (not consumers). These skip power/ground validation.
    # =========================================================================
    POWER_SUPPLY_IC_PATTERNS = {
        'generic_keywords': [
            'REGULATOR', 'LDO', 'BUCK', 'BOOST', 'FLYBACK', 'FORWARD',
            'CHARGE PUMP', 'VOLTAGE REGULATOR', 'DC-DC', 'DC/DC', 'AC-DC', 'AC/DC',
            'POWER SUPPLY', 'POWER MANAGEMENT', 'PMIC', 'PMU',
            'TRANSFORMER', 'BRIDGE', 'RECTIFIER',
            'INVERTER', 'CONVERTER', 'SWITCHING',
        ],
        'linear_reg_patterns': [
            r'LM78\d{2}', r'LM79\d{2}', r'78L?\d{2}', r'79L?\d{2}',
            r'UA78\d{2}', r'MC78\d{2}', r'MC79\d{2}',
            r'LM31[0-9]', r'LM33[0-9]', r'LM11[0-9]{2}',
            r'LM27\d{2}', r'LM29\d{2}', r'LM51\d{2}', r'LM26\d{2}',
        ],
        'ldo_patterns': [
            r'AMS11\d{2}', r'MCP17\d{2}', r'AP21\d{2}', r'TLV11\d{2}',
            r'LP29\d{2}', r'SPX11\d{2}', r'NCP11\d{2}', r'RT90\d{2}',
            r'XC62\d{2}', r'HT73\d{2}', r'ME61\d{2}', r'SGM20\d{2}',
        ],
        'switching_patterns': [
            r'TPS\d{4,5}', r'LTC\d{4}', r'LT\d{4}', r'MAX\d{4,5}',
            r'MP\d{4}', r'RT\d{4}', r'SY\d{4}', r'AOZ\d{4}',
            r'NCP\d{4}', r'AP\d{4}', r'ISL\d{4,5}', r'XL\d{4}',
        ],
        'charge_pump_patterns': [
            r'ICL766\d', r'MAX66\d', r'LTC104\d', r'TC7660',
            r'LM27\d{2}', r'TPS60\d{2,3}',
        ],
        'power_prefixes': [
            'LM', 'TPS', 'LTC', 'LT', 'MAX', 'AMS', 'MCP', 'AP', 'RT', 'MP',
        ],
    }

    # =========================================================================
    # NEGATIVE RAIL IC PATTERNS (February 2026 — Fix J.F)
    # =========================================================================
    # Regex patterns and keywords for detecting ICs that operate on negative
    # voltage rails (don't need classical GND).
    # =========================================================================
    NEGATIVE_RAIL_IC_PATTERNS = [
        r'LM79\d{2}', r'79L?\d{2}', r'MC79\d{2}', r'UA79\d{2}',
        r'LM33[7-9]', r'LT1175', r'LT1964', r'LT3090',
    ]

    NEGATIVE_RAIL_IC_KEYWORDS = [
        'NEGATIVE REGULATOR', 'NEGATIVE LDO', 'NEG REG', 'NEG LDO',
        '-V REGULATOR', 'MINUS VOLTAGE', 'INVERTING REGULATOR',
    ]

    # =========================================================================
    # DESIGN ITERATION ARTIFACT DETECTION (February 2026 — Fix X.2)
    # =========================================================================
    # AI models sometimes leave design iteration leftovers as real components.
    # Examples: Q1_REPLACED, R3_OLD, U2_BACKUP, C5_ORIGINAL, L1_REMOVED.
    # These are NOT real components — they are thinking artifacts from the AI's
    # iterative design process. The postprocessor detects and removes them.
    #
    # GENERIC: These patterns apply to ALL circuit types and component types.
    # =========================================================================

    # Ref designator suffix patterns indicating design iteration artifacts.
    # Matched against the LAST segment after rsplit('_', 1) on the ref.
    DESIGN_ARTIFACT_REF_SUFFIXES = frozenset({
        'REPLACED', 'OLD', 'BACKUP', 'ORIGINAL', 'REMOVED',
        'DELETED', 'UNUSED', 'DEPRECATED', 'PREV', 'PREVIOUS',
        'V1', 'V2', 'V3',  # Version suffixes (Q1_V2)
        'ALT', 'ALTERNATE', 'TEMP', 'TMP',
    })

    # Full-word substrings in component value/name that indicate artifacts.
    # Checked case-insensitively against component 'value' and 'name' fields.
    DESIGN_ARTIFACT_VALUE_KEYWORDS = frozenset({
        'replaced', 'removed', 'deleted', 'deprecated', 'unused',
        'do not place', 'dnp', 'no stuff', 'not stuffed',
        'placeholder', 'dummy',
    })

    # =========================================================================
    # OPTOCOUPLER EXEMPTION (February 2026 — Fix III.2)
    # =========================================================================
    # Optocouplers have LED anode/cathode + transistor emitter/collector.
    # They do NOT have VCC/GND pins like regular ICs. Exempt them from
    # the power connection checks (similar to relays).
    # Patterns are matched against component value (uppercase).
    # =========================================================================
    OPTOCOUPLER_PART_PATTERNS = [
        'PC817', 'PC827', 'PC837', 'PC847',
        'TLP521', 'TLP621', 'TLP281', 'TLP291',
        '4N25', '4N26', '4N27', '4N28', '4N33', '4N35', '4N36', '4N37',
        'MOC3020', 'MOC3021', 'MOC3022', 'MOC3023',
        'MOC3041', 'MOC3042', 'MOC3043',
        '6N135', '6N136', '6N137', '6N138', '6N139',
        'HCPL', 'ACPL',  # Avago/Broadcom families (prefix match)
        'FOD', 'CNY17', 'CNY65', 'IL300', 'OPTOCOUPLER',
        'OPTO_ISOLATOR', 'PHOTOCOUPLER',
    ]

    # =========================================================================
    # INTERFACE NET PATTERNS (February 2026 — Fix J.C, merged IV.1 + supervisor)
    # =========================================================================
    # Unified interface signal patterns for single-ended net classification.
    # Nets matching these patterns are external interfaces, not internal errors.
    # Used by circuit_supervisor._check_single_ended_nets() and
    # tests/analyze_lowlevel_circuits.py.
    # =========================================================================
    INTERFACE_NET_PATTERNS = [
        # Communication buses (protocol prefixes)
        'SPI_', 'I2C_', 'UART_', 'USB_', 'CAN_', 'RS232', 'RS485', 'LIN_',
        'MOSI', 'MISO', 'SCK', 'SCL', 'SDA', 'SS', 'CS',
        'TX', 'RX', 'TXD', 'RXD', 'DTR', 'RTS', 'CTS', 'DSR',
        'CBUS', 'FT_', 'MDIO', 'MDC',
        # N.2 FIX: UART modem control signals (Ring Indicator, Data Carrier Detect)
        'DCD', 'SPU', 'SPD',
        # Data/address buses
        'BUS_', 'DATA_', 'ADDR_', 'D0', 'D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7',
        'A0', 'A1', 'A2', 'A3', 'A4', 'A5',
        # Module and channel interfaces (generic numbered prefixes)
        'MOD', 'CH', 'CHANNEL',
        # External signals
        'EXT_', 'EXTERNAL',
        '_CTRL', '_ENABLE', '_FAULT', '_LOCK', '_PHASE',
        '_SENSE', '_FB', '_MODE', '_AUTO', '_MANUAL',
        '_GAIN', '_FREQ', '_DIAG',
        # N.2 FIX: Bare control signal keywords (complement suffix patterns above)
        'ENABLE', 'FAULT', 'RESET', 'SHUTDOWN', 'EMERGENCY',
        'PWM', 'CTRL', 'CONTROL',
        # N.2 FIX: Sense signals (bare forms complement _SENSE suffix)
        'SENSE', 'V_SENSE', 'I_SENSE',
        # Debug interfaces
        'SWDIO', 'SWCLK', 'JTAG', 'SWO', 'TDI', 'TDO', 'TMS', 'TCK',
        # Analog interfaces
        'DAC_', 'ADC_', 'ANALOG_',
        # N.2 FIX: UI / display / indicator signals
        'DISPLAY', 'LED', 'SWITCH', 'BUTTON',
        # N.2 FIX: Status / fan / signal identifiers
        'STATUS', '_STATUS', 'FAN_', '_SIGNAL', 'SIGNAL_',
        # Mechanical / thermal
        'HS', 'HEATSINK', 'TAB', 'CHASSIS', 'EARTH', 'PE_',
        # Transformer / inductor interfaces
        'XFMR_', 'SEC_', 'PRI_', 'MATCH_',
        # Debug / spare / reserved / test (from old SINGLE_ENDED_INTERFACE_KEYWORDS)
        'DEBUG', 'SPARE', 'RESERVED', 'TEST',
        # M.4 FIX: Power management, DDS, bias signals cross module boundaries
        'PGOOD', 'UVLO', 'OVP', 'OCP', 'DDS_', 'BIAS',
        '_CONDITIONED', '_FILTERED', '_BUFFERED',
        # N.2 FIX: Power domain signals (cross-module power rails)
        'VCC', 'VDD', 'GND', 'VSS', 'VEE', 'AGND', 'DGND', 'PGND',
        '+5V', '+12V', '+15V', '+24V', '+180V', '-180V', '-15V',
        '5V', '12V', '15V', '24V', '180V', '3V3', '3.3V',
        'DC_', '_DC', 'AC_', 'RAW', 'FILT',
        # N.2 FIX: Voltage reference, user/amplitude controls
        'VREF', 'USER_', 'AMPLITUDE',
        # N.2 FIX: System/global prefixes (complement SYS_NET_PREFIX check)
        'SYS_', 'GLOBAL_',
        # Q.1b FIX: Missing interface signal patterns found in forensic runs
        'ETH_', 'RMII', 'MII_',        # Ethernet interface (RGMII, RMII, MII)
        'TRANSDUCER', '_MCU',           # Transducer signals, cross-module MCU signals
        '_RAIL',                        # Power rail cross-module connections
        # V.5 FIX: Power stage signals (H-bridge, half-bridge, buck/boost)
        'BRIDGE', 'HALF_BRIDGE', 'GATE_', 'BOOT', 'BOOST',
        'HIGH_SIDE', 'LOW_SIDE', 'HS_', 'LS_',
        # V.5 FIX: Adjustment and feedback (voltage/current regulation)
        'ADJ', 'VADJ', 'IADJ', 'TRIM', 'SET_',
        # V.5 FIX: Current sensing
        'SHUNT', 'CSENSE', 'ISENSE',
        # V.5 FIX: Protection and monitoring
        'FUSE', 'MONITOR', '_MON', 'TEMP_', 'THERMAL',
        'OTP', 'UVP', 'TRIP',
        # V.5 FIX: Motor/actuator control
        'MOTOR_', 'PHASE_', 'HALL_',
        # V.5 FIX: Audio
        'SPEAKER', 'AMP_OUT', 'AUDIO_',
        # X.3 FIX: Voltage return / current return paths (power electronics)
        '_RTN', '_RET', 'RETURN_',
        # X.3 FIX: Power good / power OK signals (all regulator types)
        'PS_GOOD', 'POWER_GOOD', 'PG_', 'PGOOD', 'PWR_OK', 'POK',
        # X.3 FIX: Transistor node signals (discrete amplifier stages)
        '_EMITTER', '_COLLECTOR', '_BASE', '_GATE', '_DRAIN', '_SOURCE',
        'EMITTER_', 'COLLECTOR_', 'BASE_', 'GATE_', 'DRAIN_', 'SOURCE_',
        # X.3 FIX: Measurement / magnitude / instrumentation
        '_MAG', '_MEAS', '_RMS', '_PEAK', '_AVG',
        'MEAS_', 'INST_', 'PROBE_',
        # X.3 FIX: Reference designator-based net names (cross-module wiring)
        'NET_',  # NET_U1_PIN3, NET_F1_1, NET_Q2_GATE
        # X.3 FIX: Clock and timing signals
        'CLK_', 'CLOCK_', 'OSC_', '_CLK', '_CLOCK',
        # X.3 FIX: Interrupt and event signals
        'IRQ_', 'INT_', '_IRQ', '_INT', 'ALERT', 'ALARM',
        # X.3 FIX: Enable/inhibit variants
        'EN_', '_EN', 'INH_', '_INH', 'STBY', 'STANDBY',
    ]

    SINGLE_ENDED_POWER_PREFIXES = [
        'VCC_', 'VDD_', '+5V_', '+3V3_', '+12V_', '+15V_', '-15V_',
        'PWR_', 'POWER_', 'SUPPLY_',
        # N.3 FIX: Voltage reference outputs cross module boundaries
        'VREF_',
    ]

    SINGLE_ENDED_OK_SUFFIXES = ('_IN', '_OUT', '_INPUT', '_OUTPUT')

    # N.5 FIX: Module name prefixes used by integration agent for net naming.
    # Nets starting with these prefixes are cross-module signals.
    # Extend this list when adding new module types.
    INTERFACE_MODULE_PREFIXES = [
        'MAI_', 'MAS_', 'DDS_', 'CHA_', 'FRO_', 'PRO_', 'POW_', 'CON_',
        'AMP_', 'DRV_', 'SEN_', 'CTR_', 'COM_', 'PSU_', 'DAC_', 'ADC_',
        # X.3 FIX: Additional generic module abbreviation prefixes
        'REG_', 'FIL_', 'MOT_', 'DSP_', 'USB_', 'ETH_', 'CAN_',
        'LED_', 'LCD_', 'MCU_', 'CPU_', 'MEM_', 'CLK_', 'OSC_',
    ]

    # =========================================================================
    # UNICODE SANITIZATION FOR SUPPLIER APIS (February 2026 — Fix IX.1)
    # =========================================================================
    # Mouser (and potentially other supplier APIs) reject non-ASCII characters
    # in search keywords.  This map converts common engineering Unicode symbols
    # to their ASCII equivalents before sending API requests.
    # =========================================================================
    UNICODE_SANITIZE_MAP = {
        '\u00b5': 'u',    # µ (micro sign) → u
        '\u03bc': 'u',    # μ (Greek mu) → u
        '\u2126': 'Ohm',  # Ω (Ohm sign) → Ohm
        '\u03a9': 'Ohm',  # Ω (Greek Omega) → Ohm
        '\u00b0': 'deg',  # ° (degree sign) → deg
        '\u00b1': '+-',   # ± (plus-minus) → +-
        '\u2013': '-',    # – (en dash) → -
        '\u2014': '-',    # — (em dash) → -
    }

    # =========================================================================
    # COMPONENT RATINGS DATABASE (Phase I — Forensic Fix 20260208)
    # =========================================================================
    # Path to an optional external JSON file containing known component ratings.
    # Users can extend the built-in database without modifying code.
    # If the file does not exist, only the built-in database is used.
    # =========================================================================
    COMPONENT_RATINGS_DB_PATH = os.getenv(
        "COMPONENT_RATINGS_DB_PATH",
        str(BASE_DIR / "data" / "component_ratings.json")
    )

    # =========================================================================
    # SCHEMATIC GENERATION CONFIGURATION
    # =========================================================================
    SCHEMATIC_THEME = {
        "colors": {
            "background": "#FFFFFF",
            "component": "#000000",
            "wire": "#000000",
            "text": "#000000",
            "pin": "#000000",
            "junction": "#000000",
            "highlight": "#FF0000"
        },
        "dimensions": {
            "grid_size": 20,
            "pin_length": 10,
            "junction_radius": 3,
            "text_size_ref": 12,
            "text_size_value": 10,
            "padding": 40
        },
        "standard_symbols": {
            "resistor": {"width": 80, "height": 30},
            "capacitor": {"width": 60, "height": 40},
            "inductor": {"width": 80, "height": 30},
            "diode": {"width": 60, "height": 40},
            "ic": {"width": 120, "height": 80},
            "connector": {"width": 60, "height": 100},
            "opamp": {"width": 100, "height": 80}
        }
    }

    # Server Configuration
    SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
    DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{STORAGE_DIR}/circuit_automation.db")

    # Redis (optional)
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    USE_REDIS = os.getenv("USE_REDIS", "false").lower() == "true"

    # Security — auto-generate a random key if SECRET_KEY env var is not set.
    # Note: without a persistent key, sessions won't survive server restarts.
    SECRET_KEY = os.getenv("SECRET_KEY") or __import__("secrets").token_urlsafe(32)

    # File Upload
    MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "10485760"))  # 10MB default
    ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".txt"}

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
    LOG_FILE = os.getenv("LOG_FILE", str(LOGS_DIR / "server.log"))

    # Cost Tracking
    TRACK_API_COSTS = os.getenv("TRACK_API_COSTS", "true").lower() == "true"
    COST_WARNING_THRESHOLD = float(os.getenv("COST_WARNING_THRESHOLD", "10.00"))

    # API costs per 1M tokens (February 2026)
    # Source: https://platform.claude.com/docs/en/about-claude/pricing
    API_COSTS = {
        ModelType.OPUS_4_6.value: {"input": 5.00, "output": 25.00},    # Opus 4.6 — same price as 4.5
        ModelType.OPUS_4_5.value: {"input": 5.00, "output": 25.00},    # Opus 4.5 — kept for env overrides
        ModelType.SONNET_4_5.value: {"input": 3.00, "output": 15.00},  # Sonnet 4.5
        ModelType.HAIKU_4_5.value: {"input": 1.00, "output": 5.00},    # Haiku 4.5
    }

    # Caching
    ENABLE_CACHE = os.getenv("ENABLE_CACHE", "true").lower() == "true"
    CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))  # 1 hour

    # Development
    ALLOW_TEST_ENDPOINTS = os.getenv("ALLOW_TEST_ENDPOINTS", "true").lower() == "true"
    ENABLE_SWAGGER_UI = os.getenv("ENABLE_SWAGGER_UI", "true").lower() == "true"

    # Request Settings
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "120"))
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    # =========================================================================
    # TC #69: TEWL (Total Estimated Wire Length) Configuration
    # =========================================================================
    # TEWL is a placement quality metric that estimates routing complexity.
    # Lower TEWL = better placement = easier routing.
    #
    # These settings control how TEWL is calculated and interpreted.
    # =========================================================================
    TEWL_CONFIG = {
        # Grid size for coordinate snapping (mm)
        "grid_schematic": 1.27,      # 50 mil standard for schematics
        "grid_pcb": 1.27,            # 50 mil standard for PCB

        # TEWL complexity thresholds (avg mm per net)
        "complexity_low": 10,        # < 10mm avg = easy routing
        "complexity_medium": 25,     # 10-25mm avg = moderate routing
        "complexity_high": 50,       # 25-50mm avg = hard routing
        # > 50mm avg = very hard routing

        # Board sizing factors based on TEWL
        "trace_width_signal": 0.25,  # mm - standard signal trace
        "trace_width_power": 0.50,   # mm - power trace
        "congestion_factor_low": 1.5,
        "congestion_factor_medium": 2.0,
        "congestion_factor_high": 2.5,
        "congestion_factor_very_high": 3.0,

        # Routing difficulty score weights (0-100 scale)
        "difficulty_weight_tewl": 0.5,      # Weight for total TEWL
        "difficulty_weight_net_count": 0.25, # Weight for net count
        "difficulty_weight_max_net": 0.25,   # Weight for longest net

        # Minimum board dimensions (mm)
        "min_board_width": 30,
        "min_board_height": 30,
        "max_board_width": 200,
        "max_board_height": 200,

        # MST (Minimum Spanning Tree) approximation factors
        "mst_factor_base": 1.0,      # Base factor for 2-pin nets
        "mst_factor_increment": 0.2, # Additional factor per extra pin
    }

    # =========================================================================
    # TC #69: Routing Configuration
    # =========================================================================
    ROUTING_CONFIG = {
        # Routing completeness thresholds
        "completeness_threshold_pass": 95.0,  # % nets routed to pass
        "completeness_threshold_warn": 80.0,  # % nets routed for warning

        # Freerouting progressive routing settings
        "progressive_threshold": 40,    # Enable progressive routing above this net count
        "signal_batch_size": 15,        # Nets per batch in progressive mode
        "freerouting_timeout": 120,     # Seconds per routing attempt

        # Manhattan router settings
        "manhattan_aggressive_fallback": True,  # Enable L-path fallback
        "manhattan_max_attempts": 3,            # Retry count

        # AI fixer settings
        "ai_fixer_max_unrouted_nets": 15,  # Max nets for AI routing fix
        "ai_fixer_retry_attempts": 2,       # Max fix attempts
    }

    # =========================================================================
    # TC #69: AI Fixer Strategy Capabilities Documentation
    # =========================================================================
    # This documents what each code fixer strategy can and cannot do.
    # Used by the AI orchestrator to select appropriate strategies.
    # =========================================================================
    FIXER_STRATEGIES = {
        1: {
            "name": "Conservative",
            "description": "Safe, minimal trace adjustments",
            "capabilities": [
                "Adjust trace widths (min 0.15mm, max 0.50mm)",
                "Layer separation (50% of nets to B.Cu)",
                "Add vias at layer transitions",
                "Fix solder mask clearances",
                "Fix component clearances",
            ],
            "limitations": [
                "Cannot fix unrouted boards (0 segments)",
                "Cannot fix placement issues",
                "Cannot re-route traces",
            ],
            "best_for": [
                "clearance violations",
                "trace width issues",
                "minor crossing violations",
            ],
        },
        2: {
            "name": "Aggressive",
            "description": "Major trace adjustments, more layer separation",
            "capabilities": [
                "Aggressive trace width adjustment (max 0.30mm)",
                "Layer separation (70% of nets to B.Cu)",
                "Identify violating nets for potential re-routing",
                "Fix solder mask clearances",
                "Fix component clearances",
            ],
            "limitations": [
                "Cannot fix unrouted boards (0 segments)",
                "Cannot fix placement issues",
                "Does not actually re-route (identifies only)",
            ],
            "best_for": [
                "multiple crossing violations",
                "shorting items",
                "moderate DRC issues",
            ],
        },
        3: {
            "name": "Full Re-route",
            "description": "Delete all traces, requires converter re-run",
            "capabilities": [
                "Delete all trace segments",
                "Delete all vias",
                "Prepare board for fresh routing",
            ],
            "limitations": [
                "Requires converter re-run after",
                "Does not actually route - only clears",
                "Cannot fix placement issues",
            ],
            "best_for": [
                "severe shorting (50+ violations)",
                "completely failed routing",
                "when strategy 1+2 failed",
            ],
        },
        4: {
            "name": "Footprint Regeneration",
            "description": "Fix pad spacing with IPC-7351B compliance",
            "capabilities": [
                "Regenerate SMD pads with correct spacing",
                "Fix solder mask bridges from pad geometry",
                "Preserve net assignments",
            ],
            "limitations": [
                "Only works for 2-pin SMD components",
                "Requires re-routing after",
                "Only fixes footprint-level issues",
            ],
            "best_for": [
                "same-component pad shorts",
                "solder mask bridges (5+)",
                "footprint geometry issues",
            ],
        },
    }

    # =========================================================================
    # TC #84: KICAD CONVERTER CONFIGURATION
    # =========================================================================
    # SINGLE SOURCE OF TRUTH for KiCad converter parameters.
    # All KiCad-specific scripts MUST import from here instead of hardcoding.
    # Manufacturing parameters (clearances, trace widths) are in:
    #   scripts/kicad/manufacturing_config.py
    # =========================================================================
    KICAD_CONFIG = {
        # =====================================================================
        # VERSION STRINGS (SINGLE SOURCE OF TRUTH)
        # =====================================================================
        # KiCad 9 format version identifiers - MUST match installed KiCad version
        "sch_version": "20250114",      # Schematic file version
        "pcb_version": "20241229",      # PCB file version
        "generator_version": "9.0",     # Generator version string

        # =====================================================================
        # FILE PATHS — auto-detected per OS, overridable via environment
        # =====================================================================
        "kicad_library_path": os.getenv("KICAD_LIBRARY_PATH", _kicad_default_paths()["library"]),
        "kicad_symbol_path": os.getenv("KICAD_SYMBOL_PATH", _kicad_default_paths()["symbols"]),
        "kicad_cli_path": os.getenv("KICAD_CLI_PATH", _kicad_default_paths()["cli"]),

        # =====================================================================
        # ROUTING CONFIGURATION
        # =====================================================================
        "routing_grid_mm": 0.1,                 # TC #81: 0.1mm routing grid
        "schematic_grid_mm": 1.27,              # 50 mil schematic grid
        "max_nets_standard_routing": 50,        # Above this, use progressive routing
        "routing_timeout_seconds": 120,         # Timeout per routing attempt
        "emergency_routing_enabled": True,      # Enable fallback direct routing
        "max_routing_retries": 3,               # Max retry attempts

        # =====================================================================
        # S-EXPRESSION GENERATION (TC #84 CRITICAL)
        # =====================================================================
        # CRITICAL: All S-expression generation MUST use sexpdata library
        # NEVER use regex for S-expression modification
        "use_sexp_builder": True,               # Enforce SExpressionBuilder usage
        "validate_sexp_before_write": True,     # Pre-write validation mandatory
        "sexp_library": "sexpdata",             # Library for S-expression handling

        # =====================================================================
        # AI FIXER CONFIGURATION
        # =====================================================================
        "ai_fixer_enabled": True,
        "ai_fixer_max_attempts": 2,
        "ai_fixer_model": os.getenv("MODEL_AI_FIXER", ModelType.SONNET_4_5.value),
        "ai_fixer_timeout": 300,                # 5 minutes per attempt

        # =====================================================================
        # VALIDATION THRESHOLDS
        # =====================================================================
        "max_drc_errors_pass": 0,               # Must be 0 for production
        "max_erc_errors_pass": 0,               # Must be 0 for production
        "quality_gate_enabled": True,           # Enforce quality gate
    }

    # =========================================================================
    # TC #84: KICAD BUG LOCATION TRACKING
    # =========================================================================
    # Track known bug-prone locations for easy maintenance and auditing.
    # Each entry documents WHERE bugs occur/occurred and their fix status.
    # =========================================================================
    KICAD_BUG_LOCATIONS = {
        "sexp_regex_corruption": {
            "file": "scripts/kicad/kicad_ai_fixer.py",
            "line": 1366,
            "function": "_regenerate_footprints_with_correct_spacing",
            "description": "Regex-based pad replacement corrupts S-expressions",
            "root_cause": "Regex pattern cannot handle nested parentheses",
            "fix_required": "Replace with SExpressionBuilder using sexpdata",
            "status": "FIXED",  # TC #84: Fixed 2025-12-15 - Now uses sexpdata for proper S-expression parsing
            "severity": "BLOCKER",
            "tc_number": "TC #84",
        },
        "string_concat_pads": {
            "file": "scripts/kicad_converter.py",
            "line": 4854,
            "function": "generate_pcb_file",
            "description": "String-based pad generation",
            "root_cause": "String concatenation can't guarantee S-expression validity",
            "fix_required": "Use SExpressionBuilder for all pad generation",
            "status": "FIXED",  # TC #84: Fixed 2025-12-15 - Now uses SExpressionBuilder
            "severity": "HIGH",
            "tc_number": "TC #84",
        },
        "ai_fixer_import": {
            "file": "scripts/kicad_converter.py",
            "line": 2201,
            "function": "attempt_auto_fix",
            "description": "Import path mismatch for sexp_parser",
            "root_cause": "Used 'scripts.kicad' instead of 'kicad' prefix",
            "fix_required": "Change to 'from kicad.sexp_parser import'",
            "status": "FIXED",
            "severity": "BLOCKER",
            "tc_number": "TC #83",
        },
        "routing_complex_circuits": {
            "file": "scripts/routing/manhattan_router.py",
            "line": 1613,
            "function": "route",
            "description": "Router fails completely for circuits with 100+ nets",
            "root_cause": "Strategy exhaustion before completing routing",
            "fix_required": "Add emergency direct routing fallback",
            "status": "FIXED",  # TC #84: Fixed 2025-12-15 - Added timeout detection + emergency routing
            "severity": "CRITICAL",
            "tc_number": "TC #84",
        },
    }

    # =========================================================================
    # EAGLE CONVERTER CONFIGURATION
    # =========================================================================
    # Env-overridable settings for Eagle .sch/.brd generation.
    # =========================================================================
    EAGLE_CONFIG = {
        # Board routing mode: "ratsnest" or "routed"
        #   "ratsnest" (default): Contactrefs only — clean starting point for
        #       manual routing in Eagle. No DRC errors from auto-routing.
        #   "routed": Auto-generate copper traces (simple point-to-point).
        #       May produce DRC clearance violations in EDA import tools.
        "board_routing_mode": os.getenv("EAGLE_BOARD_ROUTING_MODE", "ratsnest"),

        # AI fixer: optionally enable via env var
        "ai_fixer_enabled": os.getenv("EAGLE_AI_FIXER", "false").lower() == "true",

        # DRC fix attempts (code-based)
        "max_drc_fix_attempts": int(os.getenv("EAGLE_MAX_DRC_FIX_ATTEMPTS", "3")),
    }

    @classmethod
    def validate(cls):
        """Validate configuration on startup"""
        errors = []

        if not cls.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is required")

        if errors:
            raise ValueError(f"Configuration errors: {'; '.join(errors)}")

        return True

    @classmethod
    def get_model_for_step(cls, step: str) -> Dict[str, Any]:
        """Get model configuration for a specific step"""
        return cls.MODELS.get(step, cls.MODELS["step_3_design_module"])

    @classmethod
    def calculate_cost(cls, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate API cost for a request"""
        if not cls.TRACK_API_COSTS:
            return 0.0

        costs = cls.API_COSTS.get(model, {"input": 5.00, "output": 25.00})
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]

        return round(input_cost + output_cost, 4)

# Create singleton instance
config = Config()
