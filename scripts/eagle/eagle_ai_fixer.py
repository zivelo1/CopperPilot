#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle AI-Based Fixer - GENERIC AI-Powered Auto-Fix for Complex ERC/DRC Errors

This module provides GENERIC AI-powered fixes for errors that code-based
fixing cannot handle. It uses Claude Sonnet 4.5 to analyze and fix issues.

Design Principles:
- GENERIC: Works for ANY circuit type (not hardcoded for specific circuits)
- CONTEXTUAL: Uses actual circuit data to understand requirements
- ADAPTIVE: AI adapts to different component types and topologies
- VALIDATED: Always re-run ERC/DRC after AI fixes

Author: AI Electronics System
Date: October 23, 2025
Version: 14.1
"""

import os
import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Add parent directory to path for config import
EAGLE_DIR = Path(__file__).parent.parent
if str(EAGLE_DIR) not in sys.path:
    sys.path.insert(0, str(EAGLE_DIR))

# Import Anthropic client (optional if using shared manager)
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    print("Warning: anthropic package not installed. Will try shared AI manager.")
    ANTHROPIC_AVAILABLE = False

# Import configuration and shared AI manager (preferred for consistency with Steps 1-4)
CONFIG_AVAILABLE = False
MANAGER_AVAILABLE = False
try:
    sys.path.insert(0, str(EAGLE_DIR.parent / "server"))
    from config import Config, ModelType
    CONFIG_AVAILABLE = True
except ImportError:
    print("Warning: config module not found. Using environment variables.")
try:
    sys.path.insert(0, str(EAGLE_DIR.parent))
    from ai_agents.agent_manager import AIAgentManager
    MANAGER_AVAILABLE = True
except Exception:
    print("Warning: AIAgentManager not available. Falling back to direct SDK.")


class AIFixer:
    """
    GENERIC AI-powered fixer for Eagle XML files.

    This fixer uses Claude Sonnet 4.5 to analyze and fix complex errors
    that deterministic code-based fixes cannot handle.

    The AI is provided with:
    - Current XML file content
    - Error messages from ERC/DRC
    - Circuit context (components, nets, topology)
    - Lowlevel circuit data (original intent)

    The AI analyzes GENERICALLY and fixes based on actual circuit requirements,
    NOT based on hardcoded assumptions.

    Usage:
        fixer = AIFixer()
        success = fixer.fix_schematic_file(sch_file, errors, circuit_context)
        if success:
            # File has been fixed by AI, re-validate
    """

    def __init__(self):
        """Initialize AI fixer.

        Prefers the shared AIAgentManager (same credentials/models as Steps 1–4)
        for consistency. Falls back to direct Anthropic SDK if manager is
        unavailable. This design is GENERIC and production‑safe.
        """
        self.manager = None
        self.client = None
        self.model = None
        self.max_tokens = 8000
        self.timeout = 120

        # Preferred: shared manager
        if MANAGER_AVAILABLE:
            try:
                self.manager = AIAgentManager()
                # Ensure it’s initialized with the same key/timeouts as the app
                self.manager.initialize()
                # Use step_3_fix_circuit model profile for fixing (closest fit)
                from server.config import config
                self.model = config.get_model_for_step('step_3_fix_circuit')['model']
            except Exception as e:
                print(f"Warning: cannot initialize AIAgentManager: {e}")
                self.manager = None

        # Fallback: direct SDK
        if not self.manager and ANTHROPIC_AVAILABLE:
            # Get API key from config or environment
            api_key = None
            if CONFIG_AVAILABLE:
                api_key = Config.ANTHROPIC_API_KEY
                self.model = ModelType.SONNET_4_5.value
            if not api_key:
                api_key = os.getenv("ANTHROPIC_API_KEY", "")
                if not self.model:
                    self.model = os.getenv("MODEL_AI_FIXER", "claude-sonnet-4-5-20250929")
            if not api_key:
                print("Warning: ANTHROPIC_API_KEY not found. AI fixing will not work.")
            else:
                self.client = anthropic.Anthropic(api_key=api_key)

        # Load prompt templates
        self._load_prompt_templates()

    def _load_prompt_templates(self):
        """Load prompt templates from ai_agents/prompts directory."""
        # Find prompts directory (go up from scripts/eagle to project root)
        project_root = EAGLE_DIR.parent  # Go up from scripts/
        prompts_dir = project_root / "ai_agents" / "prompts"

        # Load schematic fix prompt
        schematic_prompt_file = prompts_dir / "AI Agent - Eagle - Fix Schematic Prompt.txt"
        try:
            with open(schematic_prompt_file, 'r', encoding='utf-8') as f:
                self.schematic_prompt_template = f.read()
        except FileNotFoundError:
            print(f"Warning: Schematic prompt template not found at {schematic_prompt_file}")
            self.schematic_prompt_template = None

        # Load board fix prompt
        board_prompt_file = prompts_dir / "AI Agent - Eagle - Fix Board Prompt.txt"
        try:
            with open(board_prompt_file, 'r', encoding='utf-8') as f:
                self.board_prompt_template = f.read()
        except FileNotFoundError:
            print(f"Warning: Board prompt template not found at {board_prompt_file}")
            self.board_prompt_template = None

    def fix_schematic_file(
        self,
        sch_file_path: str,
        errors: List[str],
        circuit_context: Optional[Dict] = None
    ) -> bool:
        """
        Use AI to fix schematic errors.

        GENERIC: Works for ANY circuit type by analyzing actual context.

        Args:
            sch_file_path: Path to .sch file
            errors: List of error strings from ERC
            circuit_context: Optional dict with circuit info:
                - 'lowlevel_file': Path to original lowlevel JSON
                - 'components': Dict of components
                - 'nets': Dict of nets

        Returns:
            True if AI successfully fixed errors, False otherwise

        Process:
            1. Read current XML file
            2. Prepare GENERIC context for AI
            3. Call Claude Sonnet 4.5 with GENERIC prompt
            4. Parse AI response (fixed XML)
            5. Validate response is valid XML
            6. Write fixed XML to file
            7. Return success status

        Note:
            This modifies the XML file in place.
            MUST re-run ERC after calling this to validate AI's work.
        """
        if not (self.manager or self.client):
            print(f"     ❌ AI client/manager not available - cannot fix")
            return False

        print(f"  🤖 AI analyzing {len(errors)} error(s)...")

        # Read current XML
        try:
            with open(sch_file_path, 'r', encoding='utf-8') as f:
                current_xml = f.read()
        except Exception as e:
            print(f"     ❌ Cannot read file: {e}")
            return False

        # Prepare GENERIC context
        context_info = self._prepare_schematic_context(sch_file_path, circuit_context)

        # Create GENERIC prompt
        prompt = self._create_schematic_fix_prompt(
            current_xml=current_xml,
            errors=errors,
            context=context_info
        )

        # Call AI
        print(f"     🌐 Calling Claude Sonnet for GENERIC fixing...")
        fixed_xml: Optional[str] = None
        try:
            if self.manager:
                # Use the same pipeline as other steps (ensures key/timeout parity)
                # Manager is async; run in a short loop runner
                import asyncio
                async def _run():
                    res = await self.manager.call_ai(
                        step_name='step_3_fix_circuit',
                        prompt=prompt,
                        context={'project_id': 'converter-fixer', 'source': 'eagle_ai_fixer'},
                        use_cache=False
                    )
                    return res.get('raw_response') or res.get('parsed_response')
                fixed_xml = asyncio.run(_run())
            elif self.client:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}]
                )
                fixed_xml = response.content[0].text.strip()
        except Exception as e:
            print(f"     ❌ AI API call failed: {e}")
            return False
        if not fixed_xml:
            print("     ❌ Empty AI response")
            return False

        # Validate AI response is valid XML
        try:
            ET.fromstring(fixed_xml)
        except ET.ParseError as e:
            print(f"     ❌ AI returned invalid XML: {e}")
            return False

        # Write fixed XML to file
        try:
            with open(sch_file_path, 'w', encoding='utf-8') as f:
                f.write(fixed_xml)
            print(f"     ✅ AI applied fixes to file")
            return True

        except Exception as e:
            print(f"     ❌ Cannot write fixed file: {e}")
            return False

    def fix_board_file(
        self,
        brd_file_path: str,
        errors: List[str],
        circuit_context: Optional[Dict] = None
    ) -> bool:
        """
        Use AI to fix board errors.

        GENERIC: Works for ANY circuit type by analyzing actual context.

        Args:
            brd_file_path: Path to .brd file
            errors: List of error strings from DRC
            circuit_context: Optional dict with circuit info

        Returns:
            True if AI successfully fixed errors, False otherwise

        Process:
            Same as fix_schematic_file but for board files.
        """
        if not (self.manager or self.client):
            print(f"     ❌ AI client/manager not available - cannot fix")
            return False

        print(f"  🤖 AI analyzing {len(errors)} error(s)...")

        # Read current XML
        try:
            with open(brd_file_path, 'r', encoding='utf-8') as f:
                current_xml = f.read()
        except Exception as e:
            print(f"     ❌ Cannot read file: {e}")
            return False

        # Prepare GENERIC context
        context_info = self._prepare_board_context(brd_file_path, circuit_context)

        # Create GENERIC prompt
        prompt = self._create_board_fix_prompt(
            current_xml=current_xml,
            errors=errors,
            context=context_info
        )

        # Call AI
        print(f"     🌐 Calling Claude Sonnet for GENERIC fixing...")
        fixed_xml: Optional[str] = None
        try:
            if self.manager:
                import asyncio
                async def _run():
                    res = await self.manager.call_ai(
                        step_name='step_3_fix_circuit',
                        prompt=prompt,
                        context={'project_id': 'converter-fixer', 'source': 'eagle_ai_fixer'},
                        use_cache=False
                    )
                    return res.get('raw_response') or res.get('parsed_response')
                fixed_xml = asyncio.run(_run())
            elif self.client:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=0.3,
                    messages=[{"role": "user", "content": prompt}]
                )
                fixed_xml = response.content[0].text.strip()
        except Exception as e:
            print(f"     ❌ AI API call failed: {e}")
            return False
        if not fixed_xml:
            print("     ❌ Empty AI response")
            return False

        # Validate AI response is valid XML
        try:
            ET.fromstring(fixed_xml)
        except ET.ParseError as e:
            print(f"     ❌ AI returned invalid XML: {e}")
            return False

        # Write fixed XML to file
        try:
            with open(brd_file_path, 'w', encoding='utf-8') as f:
                f.write(fixed_xml)
            print(f"     ✅ AI applied fixes to file")
            return True

        except Exception as e:
            print(f"     ❌ Cannot write fixed file: {e}")
            return False

    # ========================================================================
    # CONTEXT PREPARATION (GENERIC - adapts to actual circuit)
    # ========================================================================

    def _prepare_schematic_context(
        self,
        sch_file_path: str,
        circuit_context: Optional[Dict]
    ) -> Dict:
        """
        Prepare GENERIC context for schematic fixing.

        This extracts actual circuit data to provide AI with context.
        Works for ANY circuit type.
        """
        context = {
            'filename': Path(sch_file_path).name,
            'component_count': 0,
            'net_count': 0,
            'component_types': [],
            'net_names': [],
            'lowlevel_data': None
        }

        # Extract component and net info from XML
        try:
            tree = ET.parse(sch_file_path)
            root = tree.getroot()

            # Count components
            parts = root.findall('.//parts/part')
            context['component_count'] = len(parts)
            context['component_types'] = list(set([
                p.get('deviceset', 'UNKNOWN') for p in parts
            ]))[:10]  # Top 10 types

            # Count nets
            nets = root.findall('.//nets/net')
            context['net_count'] = len(nets)
            context['net_names'] = [n.get('name', 'UNKNOWN') for n in nets[:10]]  # First 10

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

    def _prepare_board_context(
        self,
        brd_file_path: str,
        circuit_context: Optional[Dict]
    ) -> Dict:
        """
        Prepare GENERIC context for board fixing.

        Similar to schematic context but for board files.
        """
        context = {
            'filename': Path(brd_file_path).name,
            'element_count': 0,
            'signal_count': 0
        }

        # Extract board info from XML
        try:
            tree = ET.parse(brd_file_path)
            root = tree.getroot()

            # Count elements
            elements = root.findall('.//board/elements/element')
            context['element_count'] = len(elements)

            # Count signals
            signals = root.findall('.//board/signals/signal')
            context['signal_count'] = len(signals)

        except Exception:
            pass

        return context

    # ========================================================================
    # PROMPT CREATION (GENERIC prompts that work for ANY circuit)
    # ========================================================================

    def _create_schematic_fix_prompt(
        self,
        current_xml: str,
        errors: List[str],
        context: Dict
    ) -> str:
        """
        Create GENERIC prompt for schematic fixing.

        This prompt works for ANY circuit type by:
        - Not assuming circuit structure
        - Using actual context data
        - Focusing on error resolution
        - Maintaining Eagle XML standards
        """
        # Use template loaded from file if available, otherwise use fallback
        if not self.schematic_prompt_template:
            print("Warning: Using fallback prompt (template file not found)")
            # Fallback prompt (same as before)
            return self._create_schematic_fix_prompt_fallback(current_xml, errors, context)

        # Format errors
        error_list = "\n".join([f"- {err}" for err in errors[:10]])
        if len(errors) > 10:
            error_list += f"\n... and {len(errors) - 10} more errors"

        # Format context
        context_str = f"""- Filename: {context['filename']}
- Components: {context['component_count']} parts
- Component types: {', '.join(context['component_types'])}
- Nets: {context['net_count']} nets
- Net names: {', '.join(context['net_names'])}"""

        # Add lowlevel data if available (shows original intent)
        if context.get('lowlevel_data'):
            lowlevel_summary = {
                'components': [c.get('refDes', c.get('ref', 'UNKNOWN'))
                              for c in context['lowlevel_data'].get('components', [])[:5]],
                'connections': len(context['lowlevel_data'].get('connections', []))
            }
            context_str += f"\n- Original Intent (lowlevel): {json.dumps(lowlevel_summary, indent=2)}"

        # Format the template with actual data
        prompt = self.schematic_prompt_template.format(
            context_info=context_str,
            error_list=error_list,
            current_xml=current_xml
        )

        return prompt

    def _create_board_fix_prompt(
        self,
        current_xml: str,
        errors: List[str],
        context: Dict
    ) -> str:
        """
        Create GENERIC prompt for board fixing.

        Similar to schematic prompt but for board files.
        """
        # Use template loaded from file if available, otherwise use fallback
        if not self.board_prompt_template:
            print("Warning: Using fallback prompt (template file not found)")
            # Fallback prompt (same as before)
            return self._create_board_fix_prompt_fallback(current_xml, errors, context)

        # Format errors
        error_list = "\n".join([f"- {err}" for err in errors[:10]])
        if len(errors) > 10:
            error_list += f"\n... and {len(errors) - 10} more errors"

        # Format context
        context_str = f"""- Filename: {context['filename']}
- Elements: {context['element_count']} components
- Signals: {context['signal_count']} nets"""

        # Format the template with actual data
        prompt = self.board_prompt_template.format(
            context_info=context_str,
            error_list=error_list,
            current_xml=current_xml
        )

        return prompt

    # ========================================================================
    # FALLBACK PROMPTS (used if template files are not found)
    # ========================================================================

    def _create_schematic_fix_prompt_fallback(
        self,
        current_xml: str,
        errors: List[str],
        context: Dict
    ) -> str:
        """Fallback schematic prompt if template file not found."""
        # Format errors
        error_list = "\n".join([f"- {err}" for err in errors[:10]])
        if len(errors) > 10:
            error_list += f"\n... and {len(errors) - 10} more errors"

        # Format context
        context_str = f"""
CIRCUIT CONTEXT (GENERIC - this could be ANY type of circuit):
- Filename: {context['filename']}
- Components: {context['component_count']} parts
- Component types: {', '.join(context['component_types'])}
- Nets: {context['net_count']} nets
- Net names: {', '.join(context['net_names'])}
"""

        # Add lowlevel data if available
        if context.get('lowlevel_data'):
            lowlevel_summary = {
                'components': [c.get('refDes', c.get('ref', 'UNKNOWN'))
                              for c in context['lowlevel_data'].get('components', [])[:5]],
                'connections': len(context['lowlevel_data'].get('connections', []))
            }
            context_str += f"\nOriginal Intent (lowlevel): {json.dumps(lowlevel_summary, indent=2)}\n"

        prompt = f"""You are an Eagle CAD expert fixing validation errors in a schematic file.

{context_str}

ERRORS FOUND (must be fixed):
{error_list}

CURRENT SCHEMATIC XML:
{current_xml}

TASK:
Fix the schematic XML to resolve ALL errors listed above.

CONSTRAINTS (CRITICAL):
1. DO NOT assume what circuit this is - use the context provided
2. DO NOT hardcode component-specific logic - work with actual components
3. PRESERVE all existing components and nets
4. ONLY fix what's broken (errors listed above)
5. Ensure wires touch pins EXACTLY (use correct pin positions)
6. Maintain valid Eagle XML format
7. Keep all Eagle-specific attributes (version, layers, etc.)

APPROACH:
1. Analyze each error and identify root cause
2. For PIN_NOT_CONNECTED errors: adjust wire endpoints to match exact pin positions
3. For WIRE_GEOMETRY errors: recalculate wire paths using proper geometry
4. For MISSING_SYMBOL errors: add required symbols to library
5. Validate your fixes preserve circuit functionality

OUTPUT:
Return ONLY the fixed Eagle XML (complete file).
NO explanations, NO markdown, JUST the XML.
Start with <?xml version="1.0" encoding="utf-8"?>
"""
        return prompt

    def _create_board_fix_prompt_fallback(
        self,
        current_xml: str,
        errors: List[str],
        context: Dict
    ) -> str:
        """Fallback board prompt if template file not found."""
        # Format errors
        error_list = "\n".join([f"- {err}" for err in errors[:10]])
        if len(errors) > 10:
            error_list += f"\n... and {len(errors) - 10} more errors"

        prompt = f"""You are an Eagle CAD expert fixing validation errors in a board file.

BOARD CONTEXT:
- Filename: {context['filename']}
- Elements: {context['element_count']} components
- Signals: {context['signal_count']} nets

ERRORS FOUND (must be fixed):
{error_list}

CURRENT BOARD XML:
{current_xml}

TASK:
Fix the board XML to resolve ALL errors listed above.

CONSTRAINTS (CRITICAL):
1. DO NOT assume board size or complexity
2. PRESERVE all existing elements and signals
3. ONLY fix what's broken (errors listed above)
4. Ensure board dimensions are complete (4 wires on layer 20)
5. Ensure all coordinates are valid numbers
6. Maintain valid Eagle XML format

OUTPUT:
Return ONLY the fixed Eagle XML (complete file).
NO explanations, NO markdown, JUST the XML.
Start with <?xml version="1.0" encoding="utf-8"?>
"""
        return prompt


# Test function
def test_ai_fixer():
    """Test the AI fixer."""
    print("Testing AI Fixer...")
    fixer = AIFixer()
    if fixer.client:
        print("✅ AI fixer initialized with Anthropic client")
        print(f"✅ Using model: {fixer.model}")
    else:
        print("⚠️  AI client not available (missing API key)")
    print("✅ GENERIC AI fixer ready for ANY circuit type")


if __name__ == "__main__":
    test_ai_fixer()
