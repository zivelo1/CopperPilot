#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad AI-Based Fixer - GENERIC AI-Powered Auto-Fix for DRC/ERC Violations

This module provides GENERIC AI-powered fixes for violations that code-based
fixing cannot handle. It uses Claude Sonnet 4.5 to analyze and fix issues.

Design Principles:
- GENERIC: Works for ANY circuit type (not hardcoded for specific circuits)
- CONTEXTUAL: Uses actual circuit data to understand requirements
- ADAPTIVE: AI adapts to different component types and topologies
- VALIDATED: Always re-run ERC/DRC after AI fixes

Author: AI Electronics System
Date: October 28, 2025
Version: 2.0 (Following Eagle AI fixer pattern)
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# TC #50 FIX 6 (2025-11-25): Import error handling utilities
try:
    from kicad.error_handling import with_retry, RecoverableError, categorize_error
    ERROR_HANDLING_AVAILABLE = True
except ImportError:
    ERROR_HANDLING_AVAILABLE = False

# Add parent directory to path for config import
KICAD_DIR = Path(__file__).parent.parent
if str(KICAD_DIR) not in sys.path:
    sys.path.insert(0, str(KICAD_DIR))

# Import Anthropic client
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    print("Warning: anthropic package not installed. AI fixing will not work.")
    ANTHROPIC_AVAILABLE = False

# Import configuration
try:
    sys.path.insert(0, str(KICAD_DIR.parent / "server"))
    from config import Config, ModelType
    CONFIG_AVAILABLE = True
except ImportError:
    print("Warning: config module not found. Using environment variables.")
    CONFIG_AVAILABLE = False

# TC #84 (2025-12-15): Central manufacturing configuration
try:
    from manufacturing_config import MANUFACTURING_CONFIG
except ImportError:
    MANUFACTURING_CONFIG = None

# ═══════════════════════════════════════════════════════════════════════════════
# TC #84 BUG WARNING: REGEX-BASED PAD REPLACEMENT IS BROKEN
# ═══════════════════════════════════════════════════════════════════════════════
# The function _regenerate_footprints_with_correct_spacing() at line ~1366 uses
# regex to replace pad definitions. This is FUNDAMENTALLY BROKEN because:
# 1. Regex pattern cannot handle nested S-expressions reliably
# 2. Partial replacements leave orphaned text creating DUPLICATE PAD DEFINITIONS
# 3. sexpdata parser then FAILS to parse the corrupted files
# 4. All subsequent code fixers FAIL because they can't parse the file
#
# FIX REQUIRED: Replace regex approach with SExpressionBuilder (Phase 1 of TC #84)
# STATUS: NEEDS_FIX - See server/config.py KICAD_BUG_LOCATIONS["sexp_regex_corruption"]
# ═══════════════════════════════════════════════════════════════════════════════


class AIFixer:
    """
    GENERIC AI-powered fixer for KiCad files.

    This fixer uses Claude Sonnet 4.5 to analyze and fix complex violations
    that deterministic code-based fixes cannot handle.

    The AI is provided with:
    - Current PCB/schematic file content
    - Error messages from ERC/DRC
    - Circuit context (components, nets, topology)
    - Lowlevel circuit data (original intent)

    The AI analyzes GENERICALLY and fixes based on actual circuit requirements,
    NOT based on hardcoded assumptions.

    Usage:
        fixer = AIFixer()
        success = fixer.fix_pcb_file(pcb_file, violations, circuit_context)
        if success:
            # File has been fixed by AI, re-validate
    """

    def __init__(self):
        """Initialize AI fixer with Anthropic client."""
        if not ANTHROPIC_AVAILABLE:
            self.client = None
            return

        # Get API key from config or environment
        # TC #47 (2025-11-25): Upgraded to Opus 4.5 for better DRC/ERC analysis
        if CONFIG_AVAILABLE:
            api_key = Config.ANTHROPIC_API_KEY
            self.model = ModelType.OPUS_4_5.value  # TC #47: Opus 4.5 for superior analysis
            self.max_tokens = 16000  # TC #47: Increased for complex fixes (Opus 4.5 supports 64K)
            self.timeout = 180  # 3 minutes for complex analysis
        else:
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            self.model = "claude-opus-4-5-20251101"  # TC #47: Opus 4.5 fallback
            self.max_tokens = 16000
            self.timeout = 180

        if not api_key:
            print("Warning: ANTHROPIC_API_KEY not found. AI fixing will not work.")
            self.client = None
            return

        self.client = anthropic.Anthropic(api_key=api_key)

        # Load prompt templates from files
        self._load_prompt_templates()

    def _call_ai_with_retry(self, prompt: str, max_attempts: int = 3) -> Optional[str]:
        """
        TC #50 FIX 6 (2025-11-25): Call AI API with automatic retry on transient failures.

        Handles:
        - API timeout
        - Rate limiting
        - Connection errors
        - Service unavailable

        Args:
            prompt: The prompt to send to Claude
            max_attempts: Maximum retry attempts (default: 3)

        Returns:
            AI response text, or None if all attempts failed
        """
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text.strip()

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Check if error is recoverable
                recoverable_patterns = [
                    'timeout', 'rate limit', 'too many requests',
                    'service unavailable', '503', '429', '502', '504',
                    'connection', 'network', 'temporary'
                ]

                is_recoverable = any(p in error_str for p in recoverable_patterns)

                if is_recoverable and attempt < max_attempts - 1:
                    delay = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                    print(f"     ⚠️  AI API error (attempt {attempt + 1}/{max_attempts}): {e}")
                    print(f"     ↻ Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    # Non-recoverable or last attempt
                    print(f"     ❌ AI API error: {e}")
                    break

        return None

    def check_api_health(self) -> bool:
        """
        TIER 0 FIX 0.3: Quick health check to determine if AI API is reachable.
        GENERIC: Works for any network configuration, any API endpoint.
        FAST: 1 second timeout, non-blocking.

        Returns:
            True if API is reachable and healthy
            False if unreachable (offline, network issues, API down)

        Saves 2-4 minutes per circuit by skipping AI attempts when API is unreachable.
        """
        if not self.client:
            return False  # Client not initialized

        try:
            # Quick ping using messages.count_tokens (fast, doesn't consume credits)
            # This is the lightest possible API call - just checks connectivity
            self.client.messages.count_tokens(
                model=self.model,
                messages=[{"role": "user", "content": "test"}]
            )
            return True  # API is reachable
        except Exception as e:
            # Any exception means API is unreachable
            # Common cases: timeout, network error, auth error, API down
            return False

    def _load_prompt_templates(self):
        """Load prompt templates from ai_agents/prompts directory."""
        # Find prompts directory (go up from scripts/kicad to project root)
        project_root = KICAD_DIR.parent  # Go up from scripts/
        prompts_dir = project_root / "ai_agents" / "prompts"

        # Load schematic fix prompt
        schematic_prompt_file = prompts_dir / "AI Agent - KiCad - Fix Schematic Prompt.txt"
        try:
            with open(schematic_prompt_file, 'r', encoding='utf-8') as f:
                self.schematic_prompt_template = f.read()
        except FileNotFoundError:
            print(f"Warning: Schematic prompt template not found at {schematic_prompt_file}")
            self.schematic_prompt_template = None

        # Load PCB fix prompt
        pcb_prompt_file = prompts_dir / "AI Agent - KiCad - Fix PCB Prompt.txt"
        try:
            with open(pcb_prompt_file, 'r', encoding='utf-8') as f:
                self.pcb_prompt_template = f.read()
        except FileNotFoundError:
            print(f"Warning: PCB prompt template not found at {pcb_prompt_file}")
            self.pcb_prompt_template = None

    def fix_pcb_file(
        self,
        pcb_file_path: str,
        violations: List[str],
        circuit_context: Optional[Dict] = None
    ) -> bool:
        """
        Use AI to fix PCB DRC violations.

        GENERIC: Works for ANY circuit type by analyzing actual context.

        Args:
            pcb_file_path: Path to .kicad_pcb file
            violations: List of DRC violation strings
            circuit_context: Optional dict with circuit info:
                - 'lowlevel_file': Path to original lowlevel JSON
                - 'components': Dict of components
                - 'nets': Dict of nets

        Returns:
            True if AI successfully fixed violations, False otherwise

        Process:
            1. Read current PCB file
            2. Prepare GENERIC context for AI
            3. Call Claude Sonnet 4.5 with GENERIC prompt
            4. Parse AI response (fixed PCB)
            5. Validate response is valid S-expression
            6. Write fixed PCB to file
            7. Return success status

        Note:
            This modifies the PCB file in place.
            MUST re-run DRC after calling this to validate AI's work.
        """
        if not self.client:
            print(f"     ❌ AI client not available - cannot fix")
            return False

        print(f"  🤖 AI analyzing {len(violations)} DRC violation(s)...")

        # Read current PCB
        try:
            with open(pcb_file_path, 'r', encoding='utf-8') as f:
                current_content = f.read()
        except Exception as e:
            print(f"     ❌ Cannot read file: {e}")
            return False

        # Prepare GENERIC context
        context_info = self._prepare_pcb_context(pcb_file_path, circuit_context)

        # Create GENERIC prompt
        prompt = self._create_pcb_fix_prompt(
            current_content=current_content,
            violations=violations,
            context=context_info
        )

        # TC #50 FIX 6: Call AI with retry logic for transient failures
        print(f"     🌐 Calling Claude Opus 4.5 for GENERIC PCB fixing...")
        fixed_content = self._call_ai_with_retry(prompt)

        if fixed_content is None:
            print(f"     ❌ AI API call failed after all retries")
            return False

        # Validate AI response is valid S-expression
        if not self._validate_kicad_sexpr(fixed_content, 'kicad_pcb'):
            print(f"     ❌ AI returned invalid KiCad PCB format")
            return False

        # Write fixed PCB to file
        try:
            with open(pcb_file_path, 'w', encoding='utf-8') as f:
                f.write(fixed_content)
            print(f"     ✅ AI applied fixes to PCB")
            return True

        except Exception as e:
            print(f"     ❌ Cannot write fixed file: {e}")
            return False

    def fix_schematic_file(
        self,
        sch_file_path: str,
        errors: List[str],
        circuit_context: Optional[Dict] = None
    ) -> bool:
        """
        Use AI to fix schematic ERC errors.

        GENERIC: Works for ANY circuit type by analyzing actual context.

        Args:
            sch_file_path: Path to .kicad_sch file
            errors: List of ERC error strings
            circuit_context: Optional dict with circuit info

        Returns:
            True if AI successfully fixed errors, False otherwise

        Process:
            Same as fix_pcb_file but for schematic files.
        """
        if not self.client:
            print(f"     ❌ AI client not available - cannot fix")
            return False

        print(f"  🤖 AI analyzing {len(errors)} ERC error(s)...")

        # Read current schematic
        try:
            with open(sch_file_path, 'r', encoding='utf-8') as f:
                current_content = f.read()
        except Exception as e:
            print(f"     ❌ Cannot read file: {e}")
            return False

        # Prepare GENERIC context
        context_info = self._prepare_schematic_context(sch_file_path, circuit_context)

        # Create GENERIC prompt
        prompt = self._create_schematic_fix_prompt(
            current_content=current_content,
            errors=errors,
            context=context_info
        )

        # TC #50 FIX 6: Call AI with retry logic for transient failures
        print(f"     🌐 Calling Claude Opus 4.5 for GENERIC schematic fixing...")
        fixed_content = self._call_ai_with_retry(prompt)

        if fixed_content is None:
            print(f"     ❌ AI API call failed after all retries")
            return False

        # Validate AI response is valid S-expression
        if not self._validate_kicad_sexpr(fixed_content, 'kicad_sch'):
            print(f"     ❌ AI returned invalid KiCad schematic format")
            return False

        # Write fixed schematic to file
        try:
            with open(sch_file_path, 'w', encoding='utf-8') as f:
                f.write(fixed_content)
            print(f"     ✅ AI applied fixes to schematic")
            return True

        except Exception as e:
            print(f"     ❌ Cannot write fixed file: {e}")
            return False

    # ========================================================================
    # CONTEXT PREPARATION (GENERIC - adapts to actual circuit)
    # ========================================================================

    def _prepare_pcb_context(
        self,
        pcb_file_path: str,
        circuit_context: Optional[Dict]
    ) -> Dict:
        """
        Prepare GENERIC context for PCB fixing.

        This extracts actual circuit data to provide AI with context.
        Works for ANY circuit type.
        """
        context = {
            'filename': Path(pcb_file_path).name,
            'footprint_count': 0,
            'net_count': 0,
            'segment_count': 0,
            'via_count': 0,
            'board_size': 'unknown',
            'lowlevel_data': None
        }

        # Extract PCB info from file
        try:
            with open(pcb_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Count footprints
            context['footprint_count'] = len(re.findall(r'\(footprint\s+', content))

            # Count nets
            net_matches = re.findall(r'\(net\s+\d+\s+"([^"]+)"\)', content)
            context['net_count'] = len(set(net_matches))

            # Count segments and vias
            context['segment_count'] = len(re.findall(r'\(segment\s+', content))
            context['via_count'] = len(re.findall(r'\(via\s+', content))

            # Get board dimensions
            rect_match = re.search(r'\(gr_rect.*?\(start\s+([\\d.-]+)\s+([\\d.-]+)\).*?\(end\s+([\\d.-]+)\s+([\\d.-]+)\)', content, re.DOTALL)
            if rect_match:
                x1, y1, x2, y2 = map(float, rect_match.groups())
                width = abs(x2 - x1)
                height = abs(y2 - y1)
                context['board_size'] = f"{width:.1f}mm x {height:.1f}mm"

        except Exception:
            pass

        # Add lowlevel data if provided
        if circuit_context and 'lowlevel_file' in circuit_context:
            try:
                lowlevel_path = circuit_context['lowlevel_file']
                with open(lowlevel_path, 'r') as f:
                    context['lowlevel_data'] = json.load(f)
            except Exception:
                pass

        return context

    def _prepare_schematic_context(
        self,
        sch_file_path: str,
        circuit_context: Optional[Dict]
    ) -> Dict:
        """
        Prepare GENERIC context for schematic fixing.

        Similar to PCB context but for schematic files.
        """
        context = {
            'filename': Path(sch_file_path).name,
            'symbol_count': 0,
            'wire_count': 0,
            'label_count': 0,
            'lowlevel_data': None
        }

        # Extract schematic info from file
        try:
            with open(sch_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Count symbols
            context['symbol_count'] = len(re.findall(r'\(symbol\s+\(lib_id\s+', content))

            # Count wires and labels
            context['wire_count'] = len(re.findall(r'\(wire\s+', content))
            context['label_count'] = len(re.findall(r'\(label\s+', content))

        except Exception:
            pass

        # Add lowlevel data if provided
        if circuit_context and 'lowlevel_file' in circuit_context:
            try:
                lowlevel_path = circuit_context['lowlevel_file']
                with open(lowlevel_path, 'r') as f:
                    context['lowlevel_data'] = json.load(f)
            except Exception:
                pass

        return context

    # ========================================================================
    # PROMPT CREATION (GENERIC prompts that work for ANY circuit)
    # ========================================================================

    def _create_pcb_fix_prompt(
        self,
        current_content: str,
        violations: List[str],
        context: Dict
    ) -> str:
        """
        Create GENERIC prompt for PCB fixing.

        This prompt works for ANY circuit type by:
        - Not assuming circuit structure
        - Using actual context data
        - Focusing on violation resolution
        - Maintaining KiCad S-expression standards
        """
        # Use template loaded from file if available, otherwise use fallback
        if not self.pcb_prompt_template:
            print("Warning: Using fallback prompt (template file not found)")
            return self._create_pcb_fix_prompt_fallback(current_content, violations, context)

        # Format violations
        error_list = "\\n".join([f"- {err}" for err in violations[:20]])
        if len(violations) > 20:
            error_list += f"\\n... and {len(violations) - 20} more violations"

        # Format context
        context_str = f"""- Filename: {context['filename']}
- Footprints: {context['footprint_count']} components
- Nets: {context['net_count']} nets
- Segments: {context['segment_count']} traces
- Vias: {context['via_count']} vias
- Board size: {context['board_size']}"""

        # Add lowlevel data if available (shows original intent)
        if context.get('lowlevel_data'):
            lowlevel_summary = {
                'components': [c.get('refDes', c.get('ref', 'UNKNOWN'))
                              for c in context['lowlevel_data'].get('components', [])[:5]],
                'connections': len(context['lowlevel_data'].get('connections', []))
            }
            context_str += f"\\n- Original Intent (lowlevel): {json.dumps(lowlevel_summary, indent=2)}"

        # Format the template with actual data
        prompt = self.pcb_prompt_template.format(
            context_info=context_str,
            error_list=error_list,
            current_content=current_content
        )

        return prompt

    def _create_schematic_fix_prompt(
        self,
        current_content: str,
        errors: List[str],
        context: Dict
    ) -> str:
        """
        Create GENERIC prompt for schematic fixing.

        Similar to PCB prompt but for schematic files.
        """
        # Use template loaded from file if available, otherwise use fallback
        if not self.schematic_prompt_template:
            print("Warning: Using fallback prompt (template file not found)")
            return self._create_schematic_fix_prompt_fallback(current_content, errors, context)

        # Format errors
        error_list = "\\n".join([f"- {err}" for err in errors[:20]])
        if len(errors) > 20:
            error_list += f"\\n... and {len(errors) - 20} more errors"

        # Format context
        context_str = f"""- Filename: {context['filename']}
- Symbols: {context['symbol_count']} components
- Wires: {context['wire_count']} wires
- Labels: {context['label_count']} labels"""

        # Add lowlevel data if available
        if context.get('lowlevel_data'):
            lowlevel_summary = {
                'components': [c.get('refDes', c.get('ref', 'UNKNOWN'))
                              for c in context['lowlevel_data'].get('components', [])[:5]],
                'connections': len(context['lowlevel_data'].get('connections', []))
            }
            context_str += f"\\n- Original Intent (lowlevel): {json.dumps(lowlevel_summary, indent=2)}"

        # Format the template with actual data
        prompt = self.schematic_prompt_template.format(
            context_info=context_str,
            error_list=error_list,
            current_content=current_content
        )

        return prompt

    # ========================================================================
    # FALLBACK PROMPTS (used if template files are not found)
    # ========================================================================

    def _create_pcb_fix_prompt_fallback(
        self,
        current_content: str,
        violations: List[str],
        context: Dict
    ) -> str:
        """Fallback PCB prompt if template file not found."""
        error_list = "\\n".join([f"- {err}" for err in violations[:20]])
        if len(violations) > 20:
            error_list += f"\\n... and {len(violations) - 20} more violations"

        prompt = f"""You are a KiCad PCB design expert fixing DRC violations.

CIRCUIT CONTEXT (GENERIC):
- Filename: {context['filename']}
- Footprints: {context['footprint_count']} components
- Nets: {context['net_count']} nets
- Segments: {context['segment_count']} traces
- Board size: {context['board_size']}

DRC VIOLATIONS:
{error_list}

CURRENT PCB:
{current_content}

TASK: Fix all violations. Use multi-layer routing (F.Cu/B.Cu), add vias, maintain clearances.

OUTPUT: Return ONLY the fixed .kicad_pcb file (complete S-expression). NO explanations.
"""
        return prompt

    def _create_schematic_fix_prompt_fallback(
        self,
        current_content: str,
        errors: List[str],
        context: Dict
    ) -> str:
        """Fallback schematic prompt if template file not found."""
        error_list = "\\n".join([f"- {err}" for err in errors[:20]])
        if len(errors) > 20:
            error_list += f"\\n... and {len(errors) - 20} more errors"

        prompt = f"""You are a KiCad schematic design expert fixing ERC errors.

CIRCUIT CONTEXT (GENERIC):
- Filename: {context['filename']}
- Symbols: {context['symbol_count']} components
- Wires: {context['wire_count']} wires

ERC ERRORS:
{error_list}

CURRENT SCHEMATIC:
{current_content}

TASK: Fix all errors. Connect unconnected pins, add no_connect flags, fix power connections.

OUTPUT: Return ONLY the fixed .kicad_sch file (complete S-expression). NO explanations.
"""
        return prompt

    # ========================================================================
    # TC #69 FIX: ROUTING FAILURE ANALYSIS
    # ========================================================================

    def analyze_routing_failure(
        self,
        pcb_file_path: str,
        routing_log: str,
        unrouted_nets: List[str],
        router_type: str = 'freerouting'
    ) -> Dict:
        """
        TC #69 FIX (2025-12-07): Analyze routing failures for targeted suggestions.

        GENERIC: Works for any circuit by analyzing actual routing patterns.

        This method analyzes routing failures from Freerouting or Manhattan router
        and provides targeted suggestions for fixing the issues.

        Args:
            pcb_file_path: Path to .kicad_pcb file
            routing_log: Raw log output from the router
            unrouted_nets: List of net names that failed to route
            router_type: 'freerouting' or 'manhattan'

        Returns:
            Dict with analysis results:
                - 'root_causes': List of identified root causes
                - 'suggestions': List of targeted fix suggestions
                - 'severity': 'low', 'medium', 'high', 'critical'
                - 'fixable_by_ai': Whether AI can potentially fix this
                - 'recommended_actions': Prioritized list of actions
        """
        print(f"  🧠 TC #69: Analyzing routing failure ({router_type})...")

        result = {
            'root_causes': [],
            'suggestions': [],
            'severity': 'unknown',
            'fixable_by_ai': False,
            'recommended_actions': [],
            'unrouted_count': len(unrouted_nets),
            'router_type': router_type
        }

        # Extract PCB metrics for context
        pcb_metrics = self._extract_pcb_metrics(pcb_file_path)
        result['pcb_metrics'] = pcb_metrics

        # Analyze based on router type
        if router_type == 'freerouting':
            self._analyze_freerouting_failure(routing_log, unrouted_nets, pcb_metrics, result)
        else:
            self._analyze_manhattan_failure(routing_log, unrouted_nets, pcb_metrics, result)

        # Determine severity based on unrouted percentage
        if pcb_metrics.get('total_nets', 0) > 0:
            unrouted_pct = (len(unrouted_nets) / pcb_metrics['total_nets']) * 100
            if unrouted_pct >= 50:
                result['severity'] = 'critical'
            elif unrouted_pct >= 25:
                result['severity'] = 'high'
            elif unrouted_pct >= 10:
                result['severity'] = 'medium'
            else:
                result['severity'] = 'low'

        # Generate recommended actions based on analysis
        result['recommended_actions'] = self._generate_routing_recommendations(result)

        print(f"     📊 Analysis complete: {len(result['root_causes'])} root causes identified")
        print(f"     📊 Severity: {result['severity']}, {len(result['suggestions'])} suggestions")

        return result

    def _extract_pcb_metrics(self, pcb_file_path: str) -> Dict:
        """
        TC #69 FIX: Extract PCB metrics for routing analysis context.

        GENERIC: Works for any PCB by parsing actual file content.
        """
        metrics = {
            'total_nets': 0,
            'total_footprints': 0,
            'board_area': 0,
            'layer_count': 2,
            'net_classes': [],
            'component_density': 0
        }

        try:
            with open(pcb_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Count nets (unique net definitions)
            net_matches = re.findall(r'\(net\s+\d+\s+"([^"]+)"\)', content)
            metrics['total_nets'] = len(set(net_matches))

            # Count footprints
            metrics['total_footprints'] = len(re.findall(r'\(footprint\s+"', content))

            # Get board dimensions
            rect_match = re.search(r'\(gr_rect.*?\(start\s+([\d.-]+)\s+([\d.-]+)\).*?\(end\s+([\d.-]+)\s+([\d.-]+)\)', content, re.DOTALL)
            if rect_match:
                x1, y1, x2, y2 = map(float, rect_match.groups())
                width = abs(x2 - x1)
                height = abs(y2 - y1)
                metrics['board_area'] = width * height
                if metrics['board_area'] > 0 and metrics['total_footprints'] > 0:
                    # Components per 100 sq mm
                    metrics['component_density'] = (metrics['total_footprints'] / metrics['board_area']) * 100

            # Count copper layers
            layer_matches = re.findall(r'\(\d+\s+"([FB]\.Cu)"', content)
            if layer_matches:
                metrics['layer_count'] = len(set(layer_matches))

            # Extract net classes
            class_matches = re.findall(r'\(net_class\s+"([^"]+)"', content)
            metrics['net_classes'] = list(set(class_matches))

        except Exception as e:
            print(f"     ⚠️  Could not extract PCB metrics: {e}")

        return metrics

    def _analyze_freerouting_failure(
        self,
        routing_log: str,
        unrouted_nets: List[str],
        pcb_metrics: Dict,
        result: Dict
    ) -> None:
        """
        TC #69 FIX: Analyze Freerouting-specific failure patterns.

        GENERIC: Analyzes log patterns, not specific circuit assumptions.
        """
        # Pattern 1: Timeout due to complexity
        if 'timeout' in routing_log.lower() or 'exceeded' in routing_log.lower():
            result['root_causes'].append('Router timeout - circuit too complex for single pass')
            result['suggestions'].append('Use progressive routing with smaller net batches')
            result['suggestions'].append('Increase routing timeout or use simpler topology')

        # Pattern 2: Memory issues
        if 'memory' in routing_log.lower() or 'heap' in routing_log.lower():
            result['root_causes'].append('Memory exhaustion during routing')
            result['suggestions'].append('Reduce net batch size in progressive routing')
            result['suggestions'].append('Route power/ground nets separately first')

        # Pattern 3: Net count threshold
        if pcb_metrics.get('total_nets', 0) > 40:
            result['root_causes'].append(f"High net count ({pcb_metrics['total_nets']} nets) strains router")
            result['suggestions'].append('Enable progressive routing by net class')

        # Pattern 4: Component density issues
        if pcb_metrics.get('component_density', 0) > 5:
            result['root_causes'].append(f"High component density ({pcb_metrics['component_density']:.1f}/100mm²)")
            result['suggestions'].append('Consider expanding board dimensions')
            result['suggestions'].append('Use multi-layer routing (4+ layers) for dense boards')

        # Pattern 5: Analyze unrouted net names for patterns
        power_nets = [n for n in unrouted_nets if any(kw in n.upper() for kw in ['VCC', 'VDD', 'GND', 'VSS', 'PWR', 'POWER'])]
        signal_nets = [n for n in unrouted_nets if n not in power_nets]

        if len(power_nets) > len(signal_nets):
            result['root_causes'].append(f"Power nets failing disproportionately ({len(power_nets)} power vs {len(signal_nets)} signal)")
            result['suggestions'].append('Route power nets first with dedicated power planes')
            result['suggestions'].append('Add power via stitching for better current paths')
        elif signal_nets:
            result['root_causes'].append(f"{len(signal_nets)} signal nets unrouted - likely congestion")
            result['suggestions'].append('Increase trace clearances to reduce congestion')
            result['suggestions'].append('Consider wider signal routing channels')

        # Determine if AI can help
        result['fixable_by_ai'] = len(unrouted_nets) < 10 and pcb_metrics.get('total_nets', 0) < 50

    def _analyze_manhattan_failure(
        self,
        routing_log: str,
        unrouted_nets: List[str],
        pcb_metrics: Dict,
        result: Dict
    ) -> None:
        """
        TC #69 FIX: Analyze Manhattan router-specific failure patterns.

        GENERIC: Analyzes patterns from any circuit's Manhattan routing attempt.
        """
        # Pattern 1: No MST paths found
        if 'no path' in routing_log.lower() or 'unreachable' in routing_log.lower():
            result['root_causes'].append('Manhattan router could not find collision-free paths')
            result['suggestions'].append('Components may be too close - adjust placement')
            result['suggestions'].append('Enable aggressive fallback routing for stubborn nets')

        # Pattern 2: Grid alignment issues
        if 'grid' in routing_log.lower() or 'snap' in routing_log.lower():
            result['root_causes'].append('Components or pads not aligned to routing grid')
            result['suggestions'].append('Ensure all coordinates snap to 1.27mm grid')

        # Pattern 3: Layer limitations
        if 'layer' in routing_log.lower() or 'single' in routing_log.lower():
            result['root_causes'].append('Single-layer routing insufficient for net count')
            result['suggestions'].append('Enable 2-layer routing with via placement')

        # Pattern 4: Collision detection too strict
        if len(unrouted_nets) > pcb_metrics.get('total_nets', 0) * 0.3:
            result['root_causes'].append('High unrouted percentage suggests overly strict collision detection')
            result['suggestions'].append('Use aggressive fallback routing with L-path topology')
            result['suggestions'].append('Consider relaxing clearance rules temporarily')

        # Pattern 5: MST complexity
        if pcb_metrics.get('total_footprints', 0) > 20:
            result['root_causes'].append(f"Complex MST with {pcb_metrics['total_footprints']} nodes")
            result['suggestions'].append('Break routing into smaller connected subsets')

        # Manhattan router is more limited than Freerouting
        result['fixable_by_ai'] = len(unrouted_nets) < 5

    def _generate_routing_recommendations(self, analysis: Dict) -> List[str]:
        """
        TC #69 FIX: Generate prioritized recommendations based on routing analysis.

        GENERIC: Recommendations based on analysis results, not circuit-specific.
        """
        recommendations = []

        severity = analysis.get('severity', 'unknown')
        unrouted_count = analysis.get('unrouted_count', 0)
        router_type = analysis.get('router_type', 'unknown')

        # Priority 1: Critical severity actions
        if severity == 'critical':
            recommendations.append('CRITICAL: Consider fundamentally different approach')
            recommendations.append('1. Expand board dimensions by 20-30%')
            recommendations.append('2. Upgrade to 4-layer PCB for better routing channels')
            recommendations.append('3. Re-evaluate component placement for routability')

        # Priority 2: High severity actions
        elif severity == 'high':
            recommendations.append('HIGH: Routing likely needs significant adjustments')
            if router_type == 'freerouting':
                recommendations.append('1. Enable progressive routing with net class batching')
                recommendations.append('2. Route power/ground nets first with wider traces')
                recommendations.append('3. Increase Freerouting timeout to 120+ seconds')
            else:
                recommendations.append('1. Enable aggressive fallback routing')
                recommendations.append('2. Switch to Freerouting for complex nets')
                recommendations.append('3. Consider Manhattan router only for simple nets')

        # Priority 3: Medium severity actions
        elif severity == 'medium':
            recommendations.append('MEDIUM: Routing achievable with adjustments')
            recommendations.append('1. Retry with increased routing attempts')
            recommendations.append('2. Adjust trace width/clearance rules')
            if unrouted_count < 10:
                recommendations.append('3. AI fixer may be able to complete remaining routes')

        # Priority 4: Low severity actions
        else:
            recommendations.append('LOW: Most routing successful, minor cleanup needed')
            recommendations.append('1. Retry failed nets with fallback router')
            recommendations.append('2. AI fixer can likely complete remaining routes')

        # Add generic recommendations
        if analysis.get('fixable_by_ai'):
            recommendations.append('✓ AI-assisted routing fix is recommended')
        else:
            recommendations.append('⚠️  AI fix unlikely to succeed - structural changes needed')

        return recommendations

    def fix_routing_issues(
        self,
        pcb_file_path: str,
        unrouted_nets: List[str],
        routing_analysis: Optional[Dict] = None
    ) -> bool:
        """
        TC #69 FIX: AI-assisted routing fix for unrouted nets.

        GENERIC: Works for any circuit by analyzing actual PCB structure.

        Args:
            pcb_file_path: Path to .kicad_pcb file
            unrouted_nets: List of net names that need routing
            routing_analysis: Optional pre-computed routing analysis

        Returns:
            True if AI successfully added routes, False otherwise
        """
        if not self.client:
            print(f"     ❌ AI client not available for routing fix")
            return False

        if len(unrouted_nets) > 15:
            print(f"     ⚠️  Too many unrouted nets ({len(unrouted_nets)}) for AI fix")
            print(f"     💡 Consider using progressive routing or expanding board")
            return False

        print(f"  🤖 AI attempting to route {len(unrouted_nets)} unrouted nets...")

        try:
            with open(pcb_file_path, 'r', encoding='utf-8') as f:
                current_content = f.read()
        except Exception as e:
            print(f"     ❌ Cannot read PCB file: {e}")
            return False

        # Prepare routing-specific prompt
        prompt = self._create_routing_fix_prompt(
            current_content=current_content,
            unrouted_nets=unrouted_nets,
            routing_analysis=routing_analysis
        )

        # Call AI with retry
        print(f"     🌐 Calling Claude Opus 4.5 for routing assistance...")
        fixed_content = self._call_ai_with_retry(prompt)

        if fixed_content is None:
            print(f"     ❌ AI routing fix failed")
            return False

        # Validate response
        if not self._validate_kicad_sexpr(fixed_content, 'kicad_pcb'):
            print(f"     ❌ AI returned invalid PCB format")
            return False

        # Verify new segments were added
        old_segment_count = len(re.findall(r'\(segment\s+', current_content))
        new_segment_count = len(re.findall(r'\(segment\s+', fixed_content))

        if new_segment_count <= old_segment_count:
            print(f"     ⚠️  AI did not add new routing segments")
            return False

        # Write fixed PCB
        try:
            with open(pcb_file_path, 'w', encoding='utf-8') as f:
                f.write(fixed_content)
            print(f"     ✅ AI added {new_segment_count - old_segment_count} new routing segments")
            return True

        except Exception as e:
            print(f"     ❌ Cannot write fixed file: {e}")
            return False

    def _create_routing_fix_prompt(
        self,
        current_content: str,
        unrouted_nets: List[str],
        routing_analysis: Optional[Dict]
    ) -> str:
        """
        TC #69 FIX: Create GENERIC prompt for routing fix.

        GENERIC: Prompt focuses on net connectivity, not specific circuit assumptions.
        """
        net_list = "\n".join([f"- {net}" for net in unrouted_nets[:20]])
        if len(unrouted_nets) > 20:
            net_list += f"\n... and {len(unrouted_nets) - 20} more"

        analysis_context = ""
        if routing_analysis:
            analysis_context = f"""
ROUTING ANALYSIS:
- Severity: {routing_analysis.get('severity', 'unknown')}
- Root causes: {', '.join(routing_analysis.get('root_causes', [])[:3])}
- Suggestions: {', '.join(routing_analysis.get('suggestions', [])[:3])}
"""

        prompt = f"""You are a KiCad PCB routing expert. Complete the routing for unrouted nets.

UNROUTED NETS ({len(unrouted_nets)} nets):
{net_list}
{analysis_context}
CURRENT PCB FILE:
{current_content}

ROUTING REQUIREMENTS:
1. Add (segment ...) entries to complete each unrouted net
2. Use standard trace widths (0.25mm for signals, 0.5mm for power)
3. Use F.Cu and B.Cu layers, add (via ...) for layer changes
4. Maintain minimum 0.2mm clearance between traces
5. Connect all pads belonging to the same net
6. Use Manhattan-style (90° angles) or 45° routing

CRITICAL RULES:
- Do NOT modify existing segments or vias
- Do NOT change footprints or pads
- Do NOT remove any existing content
- ONLY ADD new (segment ...) and (via ...) entries
- Each segment needs: (start x y) (end x y) (width w) (layer "F.Cu") (net N)

OUTPUT: Return ONLY the complete fixed .kicad_pcb file. NO explanations."""

        return prompt

    # ========================================================================
    # VALIDATION
    # ========================================================================

    def _validate_kicad_sexpr(self, content: str, expected_type: str) -> bool:
        """
        Validate that content is a valid KiCad S-expression of expected type.

        Args:
            content: The content to validate
            expected_type: 'kicad_pcb' or 'kicad_sch'

        Returns:
            True if valid, False otherwise
        """
        # Check starts with expected type
        if not content.strip().startswith(f'({expected_type}'):
            return False

        # Check balanced parentheses
        depth = 0
        for char in content:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            if depth < 0:
                return False

        return depth == 0


def fix_kicad_circuit_ai(pcb_file: Path, sch_file: Path, attempt: int,
                        drc_report: str = "", erc_report: str = "",
                        previous_strategies: List[int] = None) -> bool:
    """
    TC #39 (2025-11-24): INTELLIGENT AI-DRIVEN FIXER - Orchestrates code fixers

    The AI Fixer is an INTELLIGENT ORCHESTRATOR that:
    1. Analyzes DRC/ERC reports to understand error patterns
    2. Decides which code fixer strategies to use (fix_kicad_circuit modes 1-3)
    3. Can call multiple code fixers in sequence if needed
    4. Makes intelligent decisions based on error types and counts

    User's architecture requirement:
    "AI Fixer module analyze the problems and uses the right scripts to fix the problems
    (since each circuit is unique and has unique problems)"

    TC #62 FIX 3.1 + 3.2 (2025-11-30): Enhanced validation handling
    - FIX 3.1: Distinguish "validation failed" from "no errors"
    - FIX 3.2: Add pre-load validation before AI analysis

    Flow:
      Validation → AI Fixer (attempt 1) → Validation →
      AI Fixer (attempt 2) → Success/TOTAL FAILURE

    Args:
        pcb_file: Path to .kicad_pcb file
        sch_file: Path to .kicad_sch file
        attempt: Attempt number (1 or 2)
        drc_report: DRC violation report (raw text from kicad-cli)
        erc_report: ERC error report (raw text from kicad-cli)

    Returns:
        True if AI decided to apply fixes (requires re-validation)
    """
    import subprocess
    import re
    from kicad.kicad_code_fixer import fix_kicad_circuit

    print(f"     🤖 AI Analysis: Reading error reports...")

    # ═══════════════════════════════════════════════════════════════════════════
    # TC #62 FIX 3.2: PRE-LOAD VALIDATION - Check if files can be loaded
    # ═══════════════════════════════════════════════════════════════════════════
    # CRITICAL: If kicad-cli cannot load the file, ERC/DRC returns 0 errors
    # but the file is ACTUALLY CORRUPTED. We must detect this!
    print(f"     🔍 Pre-Load Validation: Checking if files are loadable...")

    kicad_cli = Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
    validation_failed = False
    load_errors = []

    if kicad_cli.exists() and sch_file.exists():
        # Check for structural issues BEFORE attempting kicad-cli
        try:
            with open(sch_file, 'r') as f:
                sch_content = f.read()

            # TC #62 FIX 0.2: Check for invalid symbol unit names (library prefix in units)
            # Pattern: (symbol "Library:Name_X_Y" where X and Y are digits - this is INVALID
            invalid_unit_pattern = re.compile(r'\(symbol "([^"]+:[^"]+)_(\d+)_(\d+)"')
            invalid_units = invalid_unit_pattern.findall(sch_content)

            if invalid_units:
                print(f"     ❌ CRITICAL: Found {len(invalid_units)} invalid symbol unit names!")
                for lib_id, unit_num, style in invalid_units[:3]:
                    print(f"        • \"{lib_id}_{unit_num}_{style}\" - has library prefix (INVALID)")
                print(f"     ⚠️  This is a GENERATOR BUG - AI fixer cannot fix structural file corruption")
                print(f"     💡 FIX: Symbol units must NOT include library prefix (e.g., 'R_0_1' not 'Device:R_0_1')")
                load_errors.append(f"Invalid symbol unit naming: {len(invalid_units)} units have library prefix")
                validation_failed = True

            # Check balanced parentheses
            open_count = sch_content.count('(')
            close_count = sch_content.count(')')
            if open_count != close_count:
                print(f"     ❌ CRITICAL: Unbalanced parentheses in schematic ({open_count} open, {close_count} close)")
                load_errors.append(f"Unbalanced parentheses")
                validation_failed = True

        except Exception as e:
            print(f"     ❌ Could not read schematic file: {e}")
            load_errors.append(f"File read error: {e}")
            validation_failed = True

    # ═══════════════════════════════════════════════════════════════════════════
    # TC #62 FIX 3.1: DISTINGUISH "VALIDATION FAILED" FROM "NO ERRORS"
    # ═══════════════════════════════════════════════════════════════════════════
    if validation_failed:
        print(f"     ❌ VALIDATION FAILED: File has structural corruption that AI fixer cannot fix")
        print(f"        Detected issues:")
        for err in load_errors:
            print(f"          • {err}")
        print(f"     ⚠️  This requires fixing the GENERATOR, not the output files")
        # Return False but with clear indication this is DIFFERENT from "no errors"
        # The caller should check the printed messages to understand the difference
        return False

    # Parse error reports to understand the problem
    drc_errors = _parse_drc_report(drc_report)
    erc_errors = _parse_erc_report(erc_report)

    total_errors = len(drc_errors) + len(erc_errors)
    print(f"     📊 Total errors: {total_errors} (DRC: {len(drc_errors)}, ERC: {len(erc_errors)})")

    if total_errors == 0:
        print(f"     ✓ No ERC/DRC errors found - files are VALID")
        print(f"     ℹ️  Nothing to fix - circuit passed validation")
        return False

    # Analyze error patterns
    error_analysis = _analyze_error_patterns(drc_errors, erc_errors)
    print(f"     🧠 AI Decision Engine: Analyzing error patterns...")

    # TC #77: Print detailed analysis for debugging
    if error_analysis.get('shorting_items_count', 0) > 0:
        print(f"        • Shorting items: {error_analysis['shorting_items_count']}")
    if error_analysis.get('tracks_crossing_count', 0) > 0:
        print(f"        • Track crossings: {error_analysis['tracks_crossing_count']}")
    if error_analysis.get('unconnected_count', 0) > 0:
        print(f"        • Unconnected items: {error_analysis['unconnected_count']}")
    if error_analysis.get('solder_mask_bridge_count', 0) > 0:
        print(f"        • Solder mask bridges: {error_analysis['solder_mask_bridge_count']}")

    # TC #77: AI decides which fixer strategies to use, considering previous attempts
    previous_strategies = previous_strategies or []
    strategies = _decide_fix_strategies(error_analysis, attempt, previous_strategies)

    if not strategies:
        print(f"     ⚠️  AI determined no code fixers can help with these errors")
        if previous_strategies:
            print(f"        (Previously tried strategies: {previous_strategies})")
        return False

    print(f"     ✅ AI selected {len(strategies)} fix strateg{'y' if len(strategies) == 1 else 'ies'}:")
    for i, (strategy, reason) in enumerate(strategies, 1):
        print(f"        {i}. Strategy {strategy}: {reason}")

    # Execute selected strategies in sequence
    fixes_applied = False
    applied_strategies = []  # TC #77: Track for return to caller

    for strategy, reason in strategies:
        print(f"\n     🔧 Executing Strategy {strategy}: {reason}")
        try:
            # TC #77 ENHANCED: Handle all strategy types
            if strategy == 4:
                # TC #48: Footprint regeneration
                success = _regenerate_footprints_with_correct_spacing(pcb_file)
            elif strategy == 5:
                # TC #77: Delete shorting traces
                success = _delete_shorting_traces(pcb_file, drc_report)
            elif strategy == 6:
                # TC #77: Delete crossing traces
                success = _delete_crossing_traces(pcb_file, drc_report)
            elif strategy == 7:
                # TC #77: Re-route only unconnected nets
                success = _reroute_unconnected_nets(pcb_file, drc_report)
            else:
                # Standard strategies 1, 2, 3
                success = fix_kicad_circuit(pcb_file, sch_file, strategy, drc_report, erc_report)

            if success:
                fixes_applied = True
                applied_strategies.append(strategy)
                print(f"        ✓ Strategy {strategy} completed")
            else:
                print(f"        ⚠️  Strategy {strategy} returned False")
        except Exception as e:
            print(f"        ❌ Strategy {strategy} failed: {e}")
            import traceback
            traceback.print_exc()
            continue

    return fixes_applied


def _regenerate_footprints_with_correct_spacing(pcb_file: Path) -> bool:
    """
    TC #48/TC #50 FIX (2025-11-25): Regenerate footprint pads with IPC-7351B compliant spacing.

    This function fixes footprints in place by:
    1. Reading current PCB file
    2. Identifying components with pad spacing violations
    3. Replacing pad definitions with correct dimensions from pad_dimensions module
    4. Writing updated PCB file

    TC #50 ENHANCEMENT: Improved regex patterns to handle more footprint variations.
    GENERIC: Works for any component type by using footprint name to determine package.

    Args:
        pcb_file: Path to .kicad_pcb file

    Returns:
        True if footprints were regenerated successfully
    """
    import re
    from pathlib import Path

    try:
        # Import pad dimensions module
        from kicad.pad_dimensions import get_pad_spec_for_footprint, SMD_2PAD_SPECS

        print(f"        ├─ Reading PCB file...")
        with open(pcb_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Track fixes applied
        fixes_applied = 0
        components_fixed = []

        # TC #50 FIX: Improved footprint extraction using S-expression parsing
        # Find each footprint block by matching balanced parentheses
        footprint_starts = [m.start() for m in re.finditer(r'\(footprint\s+"', content)]

        for start in footprint_starts:
            # Extract complete footprint block by counting parentheses
            depth = 0
            end = start
            for i in range(start, len(content)):
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break

            footprint_full = content[start:end]

            # Extract footprint name
            name_match = re.match(r'\(footprint\s+"([^"]+)"', footprint_full)
            if not name_match:
                continue
            footprint_name = name_match.group(1)

            # Count pads in this footprint
            pad_count = len(re.findall(r'\(pad\s+', footprint_full))

            # Get pad spec for this footprint
            pad_spec = get_pad_spec_for_footprint(footprint_name, pad_count)

            # For 2-pin SMD components, we know the exact spacing from SMD_2PAD_SPECS
            if pad_count == 2 and pad_spec.pad_type == 'smd':
                # TC #50 FIX: More robust size code extraction
                size_code = None

                # Try multiple patterns for size code
                # Pattern 1: _0805_ or _0805Metric
                match = re.search(r'[_:](\d{4})(?:_|$|Metric|[A-Za-z])', footprint_name)
                if match:
                    size_code = match.group(1)
                # Pattern 2: Package name like "0805" standalone
                if not size_code:
                    match = re.search(r'(?:^|[/_\-:])(\d{4})(?:$|[/_\-:])', footprint_name)
                    if match:
                        size_code = match.group(1)

                if size_code and size_code in SMD_2PAD_SPECS:
                    pad_w, pad_h, center_to_center = SMD_2PAD_SPECS[size_code]

                    # Calculate pad positions (centered at 0, pads at ±half_spacing)
                    half_spacing = center_to_center / 2

                    # =====================================================================
                    # TC #84 FIX: Use sexpdata for PROPER S-expression manipulation
                    # REPLACES BROKEN REGEX-BASED PAD REPLACEMENT
                    # =====================================================================
                    # The old regex pattern could NOT handle nested S-expressions,
                    # causing DUPLICATE PAD DEFINITIONS and file corruption.
                    # Now we use sexpdata to properly parse and rebuild pads.
                    # =====================================================================
                    try:
                        import sexpdata
                        from sexpdata import Symbol
                        from kicad.sexp_builder import get_builder as get_sexp_builder

                        # Parse the footprint S-expression properly
                        footprint_sexp = sexpdata.loads(footprint_full)

                        # Find existing net assignments from pads (preserve connectivity)
                        pad1_net = None
                        pad2_net = None

                        # Helper to find net info from a pad sexp
                        def extract_net_from_pad(pad_sexp):
                            """Extract (net_num, net_name) from pad S-expression."""
                            for item in pad_sexp:
                                if isinstance(item, list) and len(item) >= 3:
                                    if isinstance(item[0], Symbol) and item[0].value() == 'net':
                                        return (item[1], item[2])
                            return None

                        # Find existing pads and extract their nets
                        pads_to_remove = []
                        for i, item in enumerate(footprint_sexp):
                            if isinstance(item, list) and len(item) >= 2:
                                if isinstance(item[0], Symbol) and item[0].value() == 'pad':
                                    pad_num = str(item[1]).strip('"')
                                    if pad_num == '1':
                                        pad1_net = extract_net_from_pad(item)
                                        pads_to_remove.append(i)
                                    elif pad_num == '2':
                                        pad2_net = extract_net_from_pad(item)
                                        pads_to_remove.append(i)

                        # Remove old pads (in reverse order to preserve indices)
                        for idx in sorted(pads_to_remove, reverse=True):
                            del footprint_sexp[idx]

                        # Use SExpressionBuilder to create NEW, VALID pads
                        sexp_builder = get_sexp_builder()

                        # TC #84: Use MANUFACTURING_CONFIG for solder_mask_margin - SINGLE SOURCE OF TRUTH
                        mask_margin = MANUFACTURING_CONFIG.PAD_TO_MASK_CLEARANCE if MANUFACTURING_CONFIG else 0.05

                        new_pad1_sexp = sexp_builder.build_pad(
                            number="1",
                            pad_type="smd",
                            shape="roundrect",
                            at=(-half_spacing, 0),
                            size=(pad_w, pad_h),
                            layers=["F.Cu", "F.Paste", "F.Mask"],
                            net=pad1_net,
                            roundrect_rratio=0.25,
                            solder_mask_margin=mask_margin
                        )

                        new_pad2_sexp = sexp_builder.build_pad(
                            number="2",
                            pad_type="smd",
                            shape="roundrect",
                            at=(half_spacing, 0),
                            size=(pad_w, pad_h),
                            layers=["F.Cu", "F.Paste", "F.Mask"],
                            net=pad2_net,
                            roundrect_rratio=0.25,
                            solder_mask_margin=mask_margin
                        )

                        # Insert new pads into footprint
                        footprint_sexp.append(new_pad1_sexp)
                        footprint_sexp.append(new_pad2_sexp)

                        # Serialize back to string
                        new_footprint = sexpdata.dumps(footprint_sexp)

                        # Replace in main content
                        content = content[:start] + new_footprint + content[end:]
                        fixes_applied += 1

                        # Extract component ref from footprint
                        ref_match = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', footprint_full)
                        ref = ref_match.group(1) if ref_match else 'UNKNOWN'
                        components_fixed.append(f"{ref} ({size_code})")

                    except Exception as e:
                        # Log error but don't crash - just skip this footprint
                        print(f"        ├─ ⚠️  Could not fix footprint {footprint_name}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue

        if fixes_applied > 0:
            print(f"        ├─ Regenerated {fixes_applied} footprints with IPC-7351B spacing")
            print(f"        ├─ Components: {', '.join(components_fixed[:5])}" +
                  (f" +{fixes_applied - 5} more" if fixes_applied > 5 else ""))

            # TC #77 Phase 3.2: VALIDATE S-expression before writing!
            # This prevents file corruption from unbalanced replacements
            from kicad.sexp_parser import validate_sexp_balance, repair_sexp_file

            is_valid, delta, msg = validate_sexp_balance(content, "footprint-regen pre-write")
            if not is_valid:
                print(f"        ├─ ⚠️  S-expression corrupted during regeneration: {msg}")
                # Attempt repair
                content, was_repaired, repair_msg = repair_sexp_file(content)
                print(f"        ├─ 🔧 Repair: {repair_msg}")

                # Validate again
                is_valid, delta, msg = validate_sexp_balance(content, "footprint-regen post-repair")
                if not is_valid:
                    print(f"        ├─ ❌ Could not repair: {msg}")
                    print(f"        └─ ABORTING footprint regeneration to prevent file corruption")
                    return False

            # Write updated content
            with open(pcb_file, 'w', encoding='utf-8') as f:
                f.write(content)

            # TC #77: Verify write was successful
            with open(pcb_file, 'r', encoding='utf-8') as f:
                written_content = f.read()
            is_valid, delta, msg = validate_sexp_balance(written_content, "footprint-regen post-write")
            if not is_valid:
                print(f"        └─ ❌ WARNING: File corrupted after write: {msg}")
                return False

            print(f"        └─ PCB file updated (validated)")
            return True
        else:
            print(f"        └─ No footprint fixes needed")
            return False

    except Exception as e:
        print(f"        ❌ Footprint regeneration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def _parse_drc_report(drc_report: str) -> List[Dict[str, str]]:
    """Parse DRC report to extract error types and details."""
    errors = []
    if not drc_report:
        return errors

    # Parse each violation line
    for line in drc_report.split('\n'):
        line = line.strip()
        if not line or line.startswith('**'):
            continue

        # Extract error type (e.g., [shorting_items], [clearance])
        if '[' in line and ']' in line:
            error_type = line[line.find('[')+1:line.find(']')]
            errors.append({'type': error_type, 'details': line})

    return errors


def _parse_erc_report(erc_report: str) -> List[Dict[str, str]]:
    """Parse ERC report to extract error types and details."""
    errors = []
    if not erc_report:
        return errors

    for line in erc_report.split('\n'):
        line = line.strip()
        if not line or line.startswith('**'):
            continue

        if '[' in line and ']' in line:
            error_type = line[line.find('[')+1:line.find(']')]
            errors.append({'type': error_type, 'details': line})

    return errors


def _analyze_error_patterns(drc_errors: List[Dict], erc_errors: List[Dict]) -> Dict:
    """
    TC #77 ENHANCED: Analyze error patterns to guide fix strategy selection.

    TC #39 (2025-11-24): Includes DFM (Design for Manufacturing) analysis
    TC #48 (2025-11-25): Added footprint pad geometry analysis
    TC #77 (2025-12-10): Added explicit shorting_items and tracks_crossing detection

    CRITICAL FIX (TC #77): Previous analysis missed explicit error type detection.
    Now we detect error types by EXACT NAME to ensure correct strategy selection.
    """
    analysis = {
        'has_shorts': False,
        'has_clearance_violations': False,
        'has_unconnected': False,
        'has_trace_issues': False,
        'has_dfm_issues': False,  # TC #39: DFM check
        'has_footprint_issues': False,  # TC #48: Footprint pad spacing check
        'short_count': 0,
        'clearance_count': 0,
        'unconnected_count': 0,
        'dfm_count': 0,  # TC #39: DFM violations
        'footprint_short_count': 0,  # TC #48: Same-component shorts
        'solder_mask_bridge_count': 0,  # TC #48: Solder mask bridges
        'severity': 'unknown',
        # TC #77: New explicit error type tracking
        'shorting_items_count': 0,  # TC #77: Cross-net shorts from routing
        'tracks_crossing_count': 0,  # TC #77: Same-layer track crossings
        'hole_clearance_count': 0,   # TC #77: Via/hole clearance issues
        'has_routing_shorts': False,  # TC #77: Shorts from bad routing
        'has_track_crossings': False,  # TC #77: Same-layer crossings
    }

    # Count error types with TC #77 explicit detection
    for error in drc_errors:
        error_type = error['type'].lower()
        error_details = error.get('details', '').lower()

        # TC #77: EXPLICIT error type matching (exact names from KiCad DRC)
        if error_type == 'shorting_items':
            analysis['has_routing_shorts'] = True
            analysis['shorting_items_count'] += 1
            analysis['has_shorts'] = True
            analysis['short_count'] += 1
            # Also check if same-component short
            if _is_same_component_short(error_details):
                analysis['has_footprint_issues'] = True
                analysis['footprint_short_count'] += 1
        elif error_type == 'tracks_crossing':
            analysis['has_track_crossings'] = True
            analysis['tracks_crossing_count'] += 1
            analysis['has_trace_issues'] = True
        elif error_type == 'hole_clearance':
            analysis['hole_clearance_count'] += 1
            analysis['has_clearance_violations'] = True
            analysis['clearance_count'] += 1
        elif error_type == 'solder_mask_bridge':
            analysis['has_footprint_issues'] = True
            analysis['solder_mask_bridge_count'] += 1
        elif error_type == 'unconnected_items':
            analysis['has_unconnected'] = True
            analysis['unconnected_count'] += 1
        elif 'clearance' in error_type:
            analysis['has_clearance_violations'] = True
            analysis['clearance_count'] += 1
        elif 'short' in error_type:  # Generic short detection
            analysis['has_shorts'] = True
            analysis['short_count'] += 1
            if _is_same_component_short(error_details):
                analysis['has_footprint_issues'] = True
                analysis['footprint_short_count'] += 1
        elif 'trace' in error_type or 'track' in error_type:
            analysis['has_trace_issues'] = True
        # TC #39: Check for DFM violations
        elif any(keyword in error_type for keyword in
                ['silk', 'drill', 'annular', 'hole', 'edge']):
            analysis['has_dfm_issues'] = True
            analysis['dfm_count'] += 1

    # TC #77: Determine severity with new error types
    total_errors = len(drc_errors) + len(erc_errors)
    shorting_total = analysis['shorting_items_count'] + analysis['short_count']
    crossing_total = analysis['tracks_crossing_count']

    # TC #77: Routing problems (shorts + crossings) are CRITICAL
    if shorting_total > 50 or crossing_total > 20:
        analysis['severity'] = 'routing_critical'
    elif total_errors > 100:
        analysis['severity'] = 'critical'
    elif total_errors > 50:
        analysis['severity'] = 'high'
    elif total_errors > 20:
        analysis['severity'] = 'medium'
    else:
        analysis['severity'] = 'low'

    # TC #39: DFM issues increase severity
    if analysis['dfm_count'] > 10:
        if analysis['severity'] in ['low', 'medium']:
            analysis['severity'] = 'high'

    # TC #48 FIX: Footprint issues are critical
    if analysis['footprint_short_count'] >= 3 or analysis['solder_mask_bridge_count'] >= 5:
        analysis['severity'] = 'footprint_critical'

    return analysis


def _is_same_component_short(error_details: str) -> bool:
    """
    TC #48 FIX (2025-11-25): Check if a shorting error is within the same component.

    Same-component shorts indicate footprint pad geometry issues, not routing issues.

    Args:
        error_details: Error details string (e.g., "pad 1 [VCC] of R1...pad 2 [NET_3] of R1")

    Returns:
        True if both pads are from the same component
    """
    import re

    # Find all component references in the error (e.g., "of R1", "of C3")
    ref_pattern = re.compile(r'of\s+([A-Z]+\d+)', re.IGNORECASE)
    matches = ref_pattern.findall(error_details)

    if len(matches) >= 2:
        # Check if any reference appears more than once
        refs = [m.upper() for m in matches]
        return len(refs) != len(set(refs))

    return False


def _decide_fix_strategies(analysis: Dict, attempt: int,
                           previous_strategies: List[int] = None) -> List[Tuple[int, str]]:
    """
    TC #77 ENHANCED: AI Decision Engine with routing-specific strategy selection.

    TC #39 (2025-11-24): Intelligent strategy selection based on error analysis
    TC #48 FIX (2025-11-25): Added strategy 4 for footprint regeneration
    TC #77 FIX (2025-12-10): Added strategies 5, 6, 7 for routing-specific errors

    CRITICAL FIX (TC #77): Previous version selected same strategies on retry.
    Now tracks previous strategies and escalates to different approaches.

    Strategy numbers map to fix_kicad_circuit modes:
      1 = Conservative (adjust trace spacing, widen traces)
      2 = Aggressive (multi-layer routing, add vias)
      3 = Full re-route (delete all traces, route from scratch)
      4 = Footprint regeneration (regenerate pads with IPC-7351B spacing)
      5 = Delete shorting traces (TC #77: remove traces causing shorts)
      6 = Delete crossing traces (TC #77: remove same-layer crossings)
      7 = Unconnected re-route (TC #77: re-route only unconnected nets)

    Args:
        analysis: Error analysis dictionary
        attempt: Attempt number (1 or 2)
        previous_strategies: List of previously attempted strategy numbers (TC #77)

    Returns:
        List of (strategy_number, reason) tuples
    """
    strategies = []
    previous_strategies = previous_strategies or []

    # TC #77: Helper to check if strategy was already tried
    def already_tried(strategy_num):
        return strategy_num in previous_strategies

    # ═══════════════════════════════════════════════════════════════════════════
    # TC #77 PRIORITY 1: ROUTING SHORTS (shorting_items)
    # ═══════════════════════════════════════════════════════════════════════════
    # These are cross-net shorts caused by bad routing - most common issue
    if analysis.get('has_routing_shorts') or analysis.get('shorting_items_count', 0) > 0:
        shorting_count = analysis.get('shorting_items_count', 0)

        if shorting_count > 100:
            # Massive shorts - need complete re-route
            if not already_tried(5):
                strategies.append((5, f"Delete {shorting_count} shorting traces (massive routing failure)"))
            if not already_tried(3):
                strategies.append((3, f"Full re-route after deleting shorts"))
        elif shorting_count > 20:
            # Significant shorts - delete offending traces
            if not already_tried(5):
                strategies.append((5, f"Delete {shorting_count} shorting traces"))
            if not already_tried(2) and attempt == 1:
                strategies.append((2, "Aggressive re-routing for affected nets"))
        else:
            # Minor shorts - try aggressive first
            if not already_tried(2):
                strategies.append((2, f"Aggressive routing to fix {shorting_count} shorts"))

    # ═══════════════════════════════════════════════════════════════════════════
    # TC #77 PRIORITY 2: TRACK CROSSINGS (tracks_crossing)
    # ═══════════════════════════════════════════════════════════════════════════
    if analysis.get('has_track_crossings') or analysis.get('tracks_crossing_count', 0) > 0:
        crossing_count = analysis.get('tracks_crossing_count', 0)

        if crossing_count > 10:
            if not already_tried(6):
                strategies.append((6, f"Delete {crossing_count} crossing track segments"))
            if not already_tried(3) and crossing_count > 50:
                strategies.append((3, "Full re-route after deleting crossings"))
        else:
            if not already_tried(2):
                strategies.append((2, f"Aggressive routing to eliminate {crossing_count} crossings"))

    # ═══════════════════════════════════════════════════════════════════════════
    # TC #48: FOOTPRINT ISSUES (must be fixed before routing)
    # ═══════════════════════════════════════════════════════════════════════════
    if analysis.get('has_footprint_issues') or analysis.get('severity') == 'footprint_critical':
        footprint_count = analysis.get('footprint_short_count', 0)
        mask_count = analysis.get('solder_mask_bridge_count', 0)
        if not already_tried(4):
            strategies.append((4, f"Footprint regeneration: {footprint_count} pad shorts, {mask_count} mask bridges"))
        if not already_tried(3):
            strategies.append((3, "Full re-route after footprint regeneration"))
        # Footprint fix is critical - return early if we have something to do
        if strategies:
            return strategies

    # ═══════════════════════════════════════════════════════════════════════════
    # TC #77 PRIORITY 3: UNCONNECTED ITEMS
    # ═══════════════════════════════════════════════════════════════════════════
    if analysis.get('has_unconnected') and analysis.get('unconnected_count', 0) > 0:
        unconnected_count = analysis.get('unconnected_count', 0)
        if not already_tried(7):
            strategies.append((7, f"Re-route {unconnected_count} unconnected nets"))

    # ═══════════════════════════════════════════════════════════════════════════
    # STANDARD ERROR HANDLING
    # ═══════════════════════════════════════════════════════════════════════════
    if not strategies:  # No routing-specific issues, use standard approach
        if attempt == 1:
            # Conservative fixes for trace/clearance issues
            if analysis['has_clearance_violations'] or analysis['has_trace_issues']:
                if not already_tried(1):
                    strategies.append((1, "Conservative trace adjustments for clearance issues"))

            # DFM issues may need conservative adjustments
            if analysis['has_dfm_issues'] and analysis['dfm_count'] < 20:
                if not already_tried(1):
                    strategies.append((1, f"Conservative fixes for {analysis['dfm_count']} DFM issues"))

            # Moderate shorts - aggressive routing
            if analysis['has_shorts'] and analysis['short_count'] < 50:
                if not already_tried(2):
                    strategies.append((2, f"Aggressive routing to resolve {analysis['short_count']} shorts"))

            # Severe shorts - full re-route
            elif analysis['has_shorts'] and analysis['short_count'] >= 50:
                if not already_tried(3):
                    strategies.append((3, f"Full re-route due to severe shorts ({analysis['short_count']}+)"))

            # Many DFM issues might need re-route
            if analysis['dfm_count'] >= 20:
                if not already_tried(3):
                    strategies.append((3, f"Full re-route to fix {analysis['dfm_count']} DFM violations"))

        else:  # attempt == 2
            # Critical severity - go straight to full re-route
            if analysis['severity'] in ['critical', 'routing_critical']:
                if not already_tried(3):
                    strategies.append((3, "Full re-route due to critical error count"))

            # Still have shorts after attempt 1 - escalate
            elif analysis['has_shorts']:
                if not already_tried(5):
                    strategies.append((5, f"Delete shorting traces (escalated)"))
                if not already_tried(3):
                    strategies.append((3, "Full re-route as last resort"))

            # Still have DFM issues - try aggressive then re-route
            elif analysis['has_dfm_issues']:
                if not already_tried(2):
                    strategies.append((2, f"Aggressive fixes for {analysis['dfm_count']} DFM issues"))
                if analysis['dfm_count'] > 10 and not already_tried(3):
                    strategies.append((3, "Full re-route for persistent DFM violations"))

            # Other errors remaining - try aggressive
            else:
                if not already_tried(2):
                    strategies.append((2, "Aggressive adjustments for remaining errors"))

    return strategies


# ═══════════════════════════════════════════════════════════════════════════════════
# TC #77: NEW STRATEGY IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════════

def _delete_shorting_traces(pcb_file: Path, drc_report: str) -> bool:
    """
    TC #77 Strategy 5: Delete traces that are causing shorting_items violations.

    This strategy parses the DRC report to find which traces are shorting to other nets,
    then removes those specific trace segments from the PCB file.

    GENERIC: Works for ANY circuit by parsing actual DRC violations.

    Args:
        pcb_file: Path to .kicad_pcb file
        drc_report: DRC report containing shorting_items violations

    Returns:
        True if traces were deleted successfully
    """
    import re

    print(f"        ├─ Parsing DRC report for shorting_items...")

    # ==========================================================================
    # TC #85 FIX: CORRECTED DRC PARSING FOR KICAD 9 FORMAT
    # ==========================================================================
    # Previous regex was WRONG - looked for: net "NET_NAME"
    # Actual KiCad DRC format is:
    #   [shorting_items]: Items shorting two nets (nets NET1 and NET2)
    #       @(X mm, Y mm): Track [NET1] on LAYER
    #       @(X mm, Y mm): Pad N [NET2] of COMPONENT on LAYER
    #
    # We use TWO parsing strategies for robustness:
    # 1. Parse from header: (nets NET1 and NET2)
    # 2. Parse from detail lines: [NET_NAME] in brackets
    # ==========================================================================

    # Strategy 1: Parse from header line - captures net names in parentheses
    header_pattern = re.compile(
        r'\[shorting_items\][^\n]*\(nets\s+(\S+)\s+and\s+(\S+)\)',
        re.IGNORECASE
    )

    # Strategy 2: Parse from detail lines - extracts net names from [brackets]
    # Format: @(X, Y): Track [NET_NAME] on LAYER ... @(X, Y): Pad N [NET_NAME]
    detail_pattern = re.compile(
        r'\[shorting_items\][^\[]*?'
        r'@[^@]+?\[([^\]]+)\][^@]*?'
        r'@[^@]+?\[([^\]]+)\]',
        re.IGNORECASE | re.DOTALL
    )

    # Try header pattern first (more reliable for net name extraction)
    shorts = header_pattern.findall(drc_report)
    parsing_method = "header"

    # Fallback to detail pattern if header didn't work
    if not shorts:
        shorts = detail_pattern.findall(drc_report)
        parsing_method = "detail"

    if not shorts:
        # TC #85: Debug output to help diagnose future parsing issues
        shorting_count = drc_report.lower().count('[shorting_items]')
        print(f"        ├─ No shorting_items found in DRC report")
        print(f"        ├─ (Debug: '{shorting_count}' [shorting_items] markers in report)")
        return False

    # Collect affected nets
    affected_nets = set()
    for net1, net2 in shorts:
        # Clean up net names (remove any trailing punctuation)
        net1_clean = net1.strip().rstrip(')')
        net2_clean = net2.strip().rstrip(')')
        affected_nets.add(net1_clean)
        affected_nets.add(net2_clean)

    print(f"        ├─ Found {len(shorts)} shorting violations affecting {len(affected_nets)} nets (parsed via {parsing_method})")

    try:
        # ==========================================================================
        # TC #86 FIX: Use SafePCBModifier with corrected delete_traces_by_net
        # ==========================================================================
        # PREVIOUS BUG: Used regex to find (net_name "...") but segments don't have that!
        # KiCad segments only have (net INDEX), not (net_name "NAME").
        #
        # FIX: Use SafePCBModifier.delete_traces_by_net() which now correctly:
        # 1. Builds net_name -> net_index mapping from net definitions
        # 2. Matches segments by net INDEX, not name
        # ==========================================================================
        from pathlib import Path
        from kicad.sexp_parser import SafePCBModifier

        modifier = SafePCBModifier(Path(pcb_file))

        original_segments = modifier.count_segments()
        original_vias = modifier.count_vias()

        # Delete traces for affected nets using corrected method
        tracks_deleted = modifier.delete_traces_by_net(list(affected_nets))

        # Also delete vias for those nets
        vias_deleted = modifier.delete_vias_by_net(list(affected_nets))

        if tracks_deleted > 0 or vias_deleted > 0:
            # Save the modified PCB
            if modifier.save(backup=True):
                final_segments = modifier.count_segments()
                final_vias = modifier.count_vias()

                print(f"        ├─ ✓ Deleted {tracks_deleted} segments, {vias_deleted} vias from {len(affected_nets)} nets")
                print(f"        ├─ Segments: {original_segments} → {final_segments}")
                print(f"        ├─ Vias: {original_vias} → {final_vias}")
                return True
            else:
                print(f"        ├─ ❌ Failed to save modified PCB")
                return False
        else:
            print(f"        ├─ No segments/vias found for affected nets")
            print(f"        ├─ (TC #86: This may indicate the nets have no routes yet)")
            return False

    except Exception as e:
        print(f"        ├─ ❌ Error deleting shorting traces: {e}")
        return False


def _delete_crossing_traces(pcb_file: Path, drc_report: str) -> bool:
    """
    TC #77 Strategy 6: Delete traces that are causing tracks_crossing violations.

    This strategy parses the DRC report to find track crossing locations,
    then removes the shorter of the two crossing segments.

    GENERIC: Works for ANY circuit by parsing actual DRC violations.

    Args:
        pcb_file: Path to .kicad_pcb file
        drc_report: DRC report containing tracks_crossing violations

    Returns:
        True if traces were deleted successfully
    """
    import re

    print(f"        ├─ Parsing DRC report for tracks_crossing...")

    # ==========================================================================
    # TC #85 FIX: CORRECTED DRC PARSING FOR KICAD 9 TRACKS_CROSSING FORMAT
    # ==========================================================================
    # Actual KiCad DRC format is:
    #   [tracks_crossing]: Tracks crossing
    #       Rule: netclass 'Default'; error
    #       @(110.3400 mm, 59.3570 mm): Track [NC_U4_7] on B.Cu, length 10.9332 mm
    #       @(98.9000 mm, 51.4600 mm): Track [SW_NODE] on B.Cu, length 23.4500 mm
    #
    # We need to extract BOTH the coordinates AND the net names for proper fixing
    # ==========================================================================

    # Pattern to extract crossing locations with coordinates
    # Format: @(X mm, Y mm): Track [NET_NAME] on LAYER
    location_pattern = re.compile(
        r'@\(([\d.]+)\s*mm,\s*([\d.]+)\s*mm\):\s*Track\s*\[([^\]]+)\]',
        re.IGNORECASE
    )

    # Find all [tracks_crossing] blocks
    crossing_blocks = re.findall(
        r'\[tracks_crossing\][^\[]*(?=\[|$)',
        drc_report,
        re.IGNORECASE | re.DOTALL
    )

    crossings = []
    crossing_nets = []

    for block in crossing_blocks:
        locations = location_pattern.findall(block)
        if len(locations) >= 2:
            # Extract coordinates from first track (crossing point)
            x, y, net1 = locations[0]
            _, _, net2 = locations[1]
            crossings.append((x, y))
            crossing_nets.append((net1, net2))

    if not crossings:
        # TC #85: Debug output to help diagnose future parsing issues
        crossing_count = drc_report.lower().count('[tracks_crossing]')
        print(f"        ├─ No tracks_crossing found in DRC report")
        print(f"        ├─ (Debug: '{crossing_count}' [tracks_crossing] markers in report)")
        return False

    print(f"        ├─ Found {len(crossings)} track crossing violations")
    print(f"        ├─ Affected nets: {set(n for pair in crossing_nets for n in pair)}")

    try:
        with open(pcb_file, 'r', encoding='utf-8') as f:
            content = f.read()

        original_length = len(content)
        tracks_deleted = 0

        # For each crossing location, find nearby track segments and delete the shorter one
        for x_str, y_str in crossings:
            try:
                cross_x = float(x_str)
                cross_y = float(y_str)

                # Find track segments near this crossing point
                # Pattern: (segment (start X Y) (end X Y) ...)
                segment_pattern = re.compile(
                    r'\(segment\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s+\(end\s+([\d.-]+)\s+([\d.-]+)\)[^)]*\)',
                    re.DOTALL
                )

                # Find segments within 2mm of crossing point
                nearby_segments = []
                for match in segment_pattern.finditer(content):
                    sx, sy = float(match.group(1)), float(match.group(2))
                    ex, ey = float(match.group(3)), float(match.group(4))

                    # Check if crossing point is near this segment
                    dist = _point_to_segment_distance(cross_x, cross_y, sx, sy, ex, ey)
                    if dist < 2.0:  # Within 2mm
                        length = ((ex - sx)**2 + (ey - sy)**2)**0.5
                        nearby_segments.append((match, length))

                # Delete the shorter segment if we found at least 2
                if len(nearby_segments) >= 2:
                    nearby_segments.sort(key=lambda x: x[1])  # Sort by length
                    shortest_match = nearby_segments[0][0]
                    content = content[:shortest_match.start()] + content[shortest_match.end():]
                    tracks_deleted += 1

            except ValueError:
                continue

        if tracks_deleted > 0:
            # TC #77: Validate S-expression before writing
            from kicad.sexp_parser import validate_sexp_balance
            is_valid, delta, msg = validate_sexp_balance(content, "post-delete")

            if not is_valid:
                print(f"        ├─ ❌ Deletion would corrupt file: {msg}")
                return False

            with open(pcb_file, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"        ├─ Deleted {tracks_deleted} crossing track segments")
            return True
        else:
            print(f"        ├─ No crossing segments could be removed")
            return False

    except Exception as e:
        print(f"        ├─ ❌ Error deleting crossing traces: {e}")
        return False


def _point_to_segment_distance(px: float, py: float,
                                x1: float, y1: float,
                                x2: float, y2: float) -> float:
    """
    TC #77: Calculate minimum distance from point to line segment.

    Uses projection onto line segment, clamped to segment endpoints.
    """
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy

    if length_sq < 1e-10:  # Segment is a point
        return ((px - x1)**2 + (py - y1)**2)**0.5

    # Project point onto line, clamped to [0, 1]
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy

    return ((px - proj_x)**2 + (py - proj_y)**2)**0.5


def _reroute_unconnected_nets(pcb_file: Path, drc_report: str) -> bool:
    """
    TC #77 Strategy 7: Re-route only unconnected nets.

    This strategy:
    1. Parses DRC report to find unconnected_items
    2. Identifies which nets have unconnected pads
    3. Deletes existing partial routes for those nets
    4. Triggers re-routing for just those nets

    GENERIC: Works for ANY circuit by parsing actual DRC violations.

    Args:
        pcb_file: Path to .kicad_pcb file
        drc_report: DRC report containing unconnected_items violations

    Returns:
        True if re-routing was triggered successfully
    """
    import re

    print(f"        ├─ Parsing DRC report for unconnected_items...")

    # ==========================================================================
    # TC #85 FIX: CORRECTED DRC PARSING FOR KICAD 9 UNCONNECTED_ITEMS FORMAT
    # ==========================================================================
    # Actual KiCad DRC format is:
    #   [unconnected_items]: Missing connection between items
    #       Local override; error
    #       @(25.4650 mm, 53.9750 mm): Track [CAP_MINUS] on F.Cu, length 1.0477 mm
    #       @(26.5100 mm, 53.9000 mm): Track [CAP_MINUS] on B.Cu, length 26.4400 mm
    #
    # The net name is in [brackets] after Track/Pad, NOT in net "..." format
    # ==========================================================================

    # Pattern to extract net names from [brackets] in unconnected_items blocks
    # Format: Track [NET_NAME] or Pad N [NET_NAME]
    net_in_brackets_pattern = re.compile(
        r'\[unconnected_items\][^\[]*?'
        r'(?:Track|Pad\s+\d+)\s*\[([^\]]+)\]',
        re.IGNORECASE | re.DOTALL
    )

    # Find all [unconnected_items] blocks and extract net names
    unconnected_blocks = re.findall(
        r'\[unconnected_items\][^\[]*(?=\[|$)',
        drc_report,
        re.IGNORECASE | re.DOTALL
    )

    matches = []
    for block in unconnected_blocks:
        # Extract all net names from this block
        nets_in_block = re.findall(
            r'(?:Track|Pad\s+\d+)\s*\[([^\]]+)\]',
            block,
            re.IGNORECASE
        )
        matches.extend(nets_in_block)

    if not matches:
        # TC #85: Debug output to help diagnose future parsing issues
        unconnected_count = drc_report.lower().count('[unconnected_items]')
        print(f"        ├─ No unconnected_items found in DRC report")
        print(f"        ├─ (Debug: '{unconnected_count}' [unconnected_items] markers in report)")
        return False

    # Get unique affected nets
    affected_nets = set(matches)
    print(f"        ├─ Found unconnected items in {len(affected_nets)} nets: {list(affected_nets)[:5]}...")

    try:
        # ==========================================================================
        # TC #86 FIX: Use SafePCBModifier with corrected delete_traces_by_net
        # ==========================================================================
        # PREVIOUS BUG: Used regex to find (net_name "...") but segments don't have that!
        # KiCad segments only have (net INDEX), not (net_name "NAME").
        #
        # FIX: Use SafePCBModifier.delete_traces_by_net() which now correctly:
        # 1. Builds net_name -> net_index mapping from net definitions
        # 2. Matches segments by net INDEX, not name
        # ==========================================================================
        from pathlib import Path
        from kicad.sexp_parser import SafePCBModifier

        modifier = SafePCBModifier(Path(pcb_file))

        original_segments = modifier.count_segments()
        original_vias = modifier.count_vias()

        # Delete ALL traces for unconnected nets
        # (Better to have no partial routes than incomplete connections)
        tracks_deleted = modifier.delete_traces_by_net(list(affected_nets))

        # Also delete vias for these nets using the corrected method
        vias_deleted = modifier.delete_vias_by_net(list(affected_nets))

        if tracks_deleted > 0 or vias_deleted > 0:
            # Save the modified PCB
            if modifier.save(backup=True):
                final_segments = modifier.count_segments()
                final_vias = modifier.count_vias()

                print(f"        ├─ ✓ Deleted {tracks_deleted} segments, {vias_deleted} vias from {len(affected_nets)} nets")
                print(f"        ├─ Segments: {original_segments} → {final_segments}")
                print(f"        ├─ Vias: {original_vias} → {final_vias}")
                print(f"        ├─ ℹ️  Re-routing will be triggered on next conversion")
                return True
            else:
                print(f"        ├─ ❌ Failed to save modified PCB")
                return False
        else:
            print(f"        ├─ No partial segments/vias to delete for unconnected nets")
            print(f"        ├─ (TC #86: This may indicate the nets have no routes yet)")
            return False

    except Exception as e:
        print(f"        ├─ ❌ Error processing unconnected nets: {e}")
        return False


# Test function
def test_ai_fixer():
    """Test the AI fixer."""
    print("Testing KiCad AI Fixer...")
    fixer = AIFixer()
    if fixer.client:
        print("✅ AI fixer initialized with Anthropic client")
        print(f"✅ Using model: {fixer.model}")
    else:
        print("⚠️  AI client not available (missing API key)")
    print("✅ GENERIC AI fixer ready for ANY circuit type")
    print("✅ TC #77: Strategies 5, 6, 7 available for routing-specific fixes")


if __name__ == "__main__":
    test_ai_fixer()
