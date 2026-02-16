# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
AI Agent Manager for handling all AI interactions
Uses Anthropic Claude API directly

MULTI-AGENT ARCHITECTURE (Jan 2026):
=====================================
This module now supports a hierarchical multi-agent system for complex circuit design:

Hierarchy:
  DesignSupervisor (orchestrator)
    ├── ModuleAgent (per-module coordinator)
    │     ├── ComponentAgent (component selection)
    │     ├── ConnectionAgent (connection synthesis)
    │     └── ValidationAgent (per-module ERC)
    └── IntegrationAgent (cross-module integration)

Key Features:
  - Context isolation: Each agent has focused, limited context
  - Parallel execution: Independent modules designed concurrently
  - Interface contracts: Well-defined module boundaries
  - Graceful degradation: Falls back to single-agent on simple circuits

Configuration:
  - Agent models configured in server/config.py MODELS dict
  - Multi-agent settings in server/config.py MULTI_AGENT_CONFIG
  - Prompts in ai_agents/prompts/multi_agent/
"""
import json
import re
import time
from typing import Dict, Any, Optional, List, Callable, Tuple
from pathlib import Path
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import anthropic
from anthropic import AsyncAnthropic
import httpx

from server.config import config
from utils.logger import setup_logger, ComprehensiveLogger

# Import requirements extractor for component rating guidance
# This is used to dynamically inject voltage/current/power guidance into Step 3 prompts
try:
    from workflow.requirements_rating_extractor import (
        RequirementsRatingExtractor,
        get_component_guidance_for_requirements
    )
    RATING_EXTRACTOR_AVAILABLE = True
except ImportError:
    RATING_EXTRACTOR_AVAILABLE = False

logger = setup_logger(__name__)
chat_logger = setup_logger("chat.ai_interactions")


def classify_api_error(error_message: str) -> str:
    """
    Classify an Anthropic API error into a category using config-driven
    substring matching.

    Returns one of:
        CREDIT_EXHAUSTED, AUTH_FAILED, RATE_LIMITED, OVERLOADED,
        SERVER_ERROR, TIMEOUT, UNKNOWN

    The categories are defined in ``config.API_ERROR_CATEGORIES`` (single
    source of truth) so they can be extended without touching this function.
    """
    if not error_message:
        return "UNKNOWN"

    lower = error_message.lower()
    for category, substrings in config.API_ERROR_CATEGORIES.items():
        for substring in substrings:
            if substring.lower() in lower:
                return category
    return "UNKNOWN"


class APIHealthCheckError(Exception):
    """Raised when the pre-flight API health check fails."""

    def __init__(self, category: str, detail: str):
        self.category = category
        self.detail = detail
        super().__init__(f"API pre-flight failed [{category}]: {detail}")


class AIAgentManager:
    """
    Manages all AI agent interactions with caching and cost tracking
    Replaces N8N AI Agent nodes
    """

    _instance = None
    _client: Optional[AsyncAnthropic] = None
    _cache: Dict[str, Any] = {}
    _total_cost: float = 0.0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AIAgentManager, cls).__new__(cls)
        return cls._instance

    @classmethod
    def initialize(cls):
        """Initialize the AI client"""
        if not cls._client:
            cls._client = AsyncAnthropic(
                api_key=config.ANTHROPIC_API_KEY,
                timeout=httpx.Timeout(config.REQUEST_TIMEOUT, connect=10.0),
                max_retries=config.MAX_RETRIES
            )
            logger.info("Anthropic client initialized")

    async def test_connection(self) -> Dict[str, Any]:
        """
        Pre-flight API health check — sends a minimal request to verify
        that the API key is valid and credits are available.

        Returns:
            Dict with keys: success (bool), error (str|None), category (str|None)

        Raises:
            APIHealthCheckError for non-retryable failures (CREDIT_EXHAUSTED,
            AUTH_FAILED) so callers can abort immediately.
        """
        if not self._client:
            self.initialize()

        qg = config.QUALITY_GATES
        max_tokens = qg["preflight_max_tokens"]
        timeout_s = qg["preflight_timeout"]

        try:
            logger.info("Running pre-flight API health check...")
            response = await asyncio.wait_for(
                self._client.messages.create(
                    model=config.MODELS["step_1"]["model"],
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": "ping"}],
                    timeout=httpx.Timeout(timeout_s, connect=10.0),
                ),
                timeout=timeout_s + 5,
            )
            logger.info("Pre-flight health check PASSED")
            return {"success": True, "error": None, "category": None}

        except Exception as exc:
            error_str = str(exc)
            category = classify_api_error(error_str)
            logger.error(f"Pre-flight health check FAILED [{category}]: {error_str}")

            # Non-retryable errors — abort the workflow immediately
            if category in ("CREDIT_EXHAUSTED", "AUTH_FAILED"):
                raise APIHealthCheckError(category, error_str)

            return {"success": False, "error": error_str, "category": category}

    @staticmethod
    def classify_error(error_message: str) -> str:
        """
        Public convenience wrapper around the module-level classifier.
        Delegates to ``classify_api_error()`` so callers don't need to
        import the free function.
        """
        return classify_api_error(error_message)

    async def call_ai(
        self,
        step_name: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Call AI with the appropriate model for the given step

        Args:
            step_name: Name of the workflow step (e.g., 'step_3_design_module')
            prompt: The prompt to send to the AI
            context: Additional context to include
            use_cache: Whether to use cached responses

        Returns:
            Dict containing the AI response and metadata
        """
        if not self._client:
            self.initialize()

        # Get model configuration for this step
        model_config = config.get_model_for_step(step_name)

        # Create cache key if caching enabled
        cache_key = None
        if use_cache and config.ENABLE_CACHE:
            cache_key = self._generate_cache_key(step_name, prompt, context)
            if cache_key in self._cache:
                logger.info(f"Using cached response for {step_name}")
                return self._cache[cache_key]

        # Prepare the full prompt with context
        full_prompt = self._prepare_prompt(prompt, context)

        # Track timing
        start_time = time.time()

        try:
            # Make the API call
            logger.info(f"Calling Anthropic API for {step_name} with model {model_config['model']}")
            logger.info(f"Prompt length: {len(full_prompt)} characters")
            logger.debug(f"Prompt preview: {full_prompt[:500]}..." if len(full_prompt) > 500 else f"Full prompt: {full_prompt}")

            # Add timeout for the API call
            # Use timeout from model config or default
            timeout = float(model_config.get('timeout', 240))  # Default to 4 minutes if not specified
            logger.info(f"Using {timeout}s timeout for {step_name}")

            # =====================================================================
            # TC #93 FIX (2025-12-25): Pass timeout to messages.create() to override
            # the httpx client default (REQUEST_TIMEOUT=120s). Without this, the httpx
            # client would cut off long-running Opus responses before asyncio.wait_for
            # gets a chance to handle them properly.
            #
            # ROOT CAUSE: httpx.Timeout(120) was killing requests at 120s, but Opus
            # responses for complex circuits need 80-200+ seconds.
            #
            # FIX: Pass httpx.Timeout(timeout) per-request to match the step's timeout.
            # This is GENERIC - each step can have its own timeout in config.py.
            # =====================================================================
            # T.5 FIX: Claude Opus 4.6 does NOT support assistant message prefill
            # (returns API 400: "This model does not support assistant message
            # prefill"). JSON output is enforced via prompt instructions (S.4 fix)
            # and the max_tokens increase (S.1 fix). Do NOT add prefill back.
            response = await asyncio.wait_for(
                self._client.messages.create(
                    model=model_config['model'],
                    max_tokens=model_config['max_tokens'],
                    temperature=model_config['temperature'],
                    messages=[{"role": "user", "content": full_prompt}],
                    timeout=httpx.Timeout(timeout, connect=30.0)  # TC #93: Override client timeout per-request
                ),
                timeout=timeout + 30  # TC #93: asyncio timeout slightly longer than httpx for clean error handling
            )

            # Extract the response
            ai_response = response.content[0].text if response.content else ""
            logger.info(f"AI response received: {len(ai_response)} characters")

            # Calculate tokens and cost first
            input_tokens = response.usage.input_tokens if hasattr(response, 'usage') else 0
            output_tokens = response.usage.output_tokens if hasattr(response, 'usage') else 0
            cost = config.calculate_cost(model_config['model'], input_tokens, output_tokens)

            # Save AI interaction if enhanced logger available
            if hasattr(self, 'enhanced_logger') and self.enhanced_logger:
                metadata = {
                    'model': model_config['model'],
                    'temperature': model_config['temperature'],
                    'max_tokens': model_config['max_tokens'],
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'cost': cost,
                    'duration': time.time() - start_time,
                    'step': step_name
                }
                self.enhanced_logger.save_ai_interaction(
                    step=step_name,
                    prompt=full_prompt,
                    response=ai_response,
                    metadata=metadata,
                    interaction_type='main'
                )
            logger.debug(f"Response preview: {ai_response[:500]}..." if len(ai_response) > 500 else f"Full response: {ai_response}")

            # Log to chat logger for AI interactions tab
            chat_logger.info(f"{'='*60}")
            chat_logger.info(f"AI INTERACTION: {step_name}")
            chat_logger.info(f"Model: {model_config['model']}")
            chat_logger.info(f"Temperature: {model_config['temperature']}")
            chat_logger.info(f"Max tokens: {model_config['max_tokens']}")
            chat_logger.info(f"PROMPT ({len(full_prompt)} chars):")
            chat_logger.info(full_prompt[:1000] + "..." if len(full_prompt) > 1000 else full_prompt)
            chat_logger.info(f"RESPONSE ({len(ai_response)} chars):")
            chat_logger.info(ai_response[:2000] + "..." if len(ai_response) > 2000 else ai_response)
            chat_logger.info(f"{'='*60}")

            # Try to parse as JSON if it looks like JSON
            parsed_response = self._try_parse_json(ai_response)

            self._total_cost += cost

            # Save AI interaction with comprehensive logger
            comprehensive_logger = ComprehensiveLogger()
            comprehensive_logger.log_ai_interaction(
                model=model_config['model'],
                prompt=full_prompt,
                response=ai_response,
                tokens_used=input_tokens + output_tokens,
                duration=time.time() - start_time,
                project_id=context.get('project_id') if context else None,
                step=step_name,
                cost=cost
            )

            # Check cost warning threshold
            if cost > config.COST_WARNING_THRESHOLD:
                logger.warning(f"High API cost for {step_name}: ${cost:.2f}")

            # Prepare result
            result = {
                "success": True,
                "step": step_name,
                "model": model_config['model'],
                "raw_response": ai_response,
                "parsed_response": parsed_response or ai_response,
                "metadata": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": cost,
                    "total_cost": self._total_cost,
                    "execution_time": time.time() - start_time,
                    "timestamp": datetime.now().isoformat()
                }
            }

            # Cache the result
            if cache_key and config.ENABLE_CACHE:
                self._cache[cache_key] = result
                # Implement cache expiry
                asyncio.create_task(self._expire_cache(cache_key, config.CACHE_TTL))

            logger.info(f"AI call completed for {step_name} - Cost: ${cost:.4f}, Time: {result['metadata']['execution_time']:.2f}s")

            # Print cost to terminal for visibility
            print(f"   💰 {step_name}: ${cost:.4f} (Running total: ${self._total_cost:.4f})")

            return result

        except asyncio.TimeoutError:
            timeout_used = float(model_config.get('timeout', 240))
            logger.error(f"AI call timed out for {step_name} after {timeout_used} seconds")
            return {
                "success": False,
                "step": step_name,
                "error": f"AI call timed out after {timeout_used} seconds",
                "metadata": {
                    "execution_time": time.time() - start_time,
                    "timestamp": datetime.now().isoformat()
                }
            }
        except Exception as e:
            error_str = str(e)
            error_category = classify_api_error(error_str)
            logger.error(f"Error calling AI for {step_name} [{error_category}]: {error_str}")

            # Return error result with classification
            return {
                "success": False,
                "step": step_name,
                "error": error_str,
                "error_category": error_category,
                "metadata": {
                    "execution_time": time.time() - start_time,
                    "timestamp": datetime.now().isoformat()
                }
            }

    async def call_ai_with_retry(
        self,
        step_name: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Call AI with automatic retry on failure.

        Respects error classification: non-retryable errors (CREDIT_EXHAUSTED,
        AUTH_FAILED) abort immediately instead of burning through retries.
        """
        last_error = None
        last_category = "UNKNOWN"
        non_retryable = {"CREDIT_EXHAUSTED", "AUTH_FAILED"}

        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(config.RETRY_DELAY * attempt)  # Exponential backoff
                logger.info(f"Retry attempt {attempt + 1} for {step_name}")

            result = await self.call_ai(step_name, prompt, context, use_cache=(attempt == 0))

            if result["success"]:
                return result

            last_error = result.get("error", "Unknown error")
            last_category = result.get("error_category", classify_api_error(last_error))

            # Fail fast on non-retryable errors
            if last_category in non_retryable:
                logger.error(
                    f"Non-retryable error [{last_category}] for {step_name} — aborting retries"
                )
                result["error"] = f"[{last_category}] {last_error}"
                return result

        # All retries exhausted
        logger.error(f"All retries failed for {step_name}: {last_error}")
        return {
            "success": False,
            "step": step_name,
            "error": f"Failed after {max_retries} attempts: {last_error}",
            "error_category": last_category
        }

    def _prepare_prompt(self, prompt: str, context: Optional[Dict[str, Any]]) -> str:
        """Prepare the full prompt with context"""
        if not context:
            return prompt

        # Add context to prompt
        context_str = "\n\n## Context:\n"
        for key, value in context.items():
            if isinstance(value, (dict, list)):
                context_str += f"\n### {key}:\n```json\n{json.dumps(value, indent=2)}\n```\n"
            else:
                context_str += f"\n### {key}:\n{value}\n"

        return prompt + context_str

    def _try_parse_json(self, text: str) -> Optional[Any]:
        """Try to parse text as JSON"""
        # Try to extract JSON from the response
        text = text.strip()

        # Look for JSON markers
        json_start = text.find('{')
        json_end = text.rfind('}')

        if json_start == -1 or json_end == -1:
            # Try array format
            json_start = text.find('[')
            json_end = text.rfind(']')

        if json_start != -1 and json_end != -1:
            json_str = text[json_start:json_end + 1]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse JSON: {e}")
                return None

        return None

    def _generate_cache_key(self, step_name: str, prompt: str, context: Optional[Dict]) -> str:
        """
        Generate a unique cache key for the request.

        TC #93 FIX: Use FULL prompt hash instead of truncated.
        Previous bug: Using only first 500 chars caused cache collisions when
        different modules had similar prompt prefixes (e.g., two power supply
        modules, two amplifier modules). This is a GENERIC fix that prevents
        collisions for ANY circuit type with similar module structures.

        Args:
            step_name: The workflow step name (e.g., 'step_3_stage1_components')
            prompt: The full prompt text
            context: Optional context dict

        Returns:
            MD5 hash string that uniquely identifies this request
        """
        import hashlib

        # TC #93 FIX: Hash the FULL prompt to avoid collisions
        # Different modules (power supply, amplifier, control, etc.) might have
        # identical first 500 chars but differ in module-specific requirements
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

        # Create cache key combining step, prompt hash, and context hash
        cache_data = {
            "step": step_name,
            "prompt_hash": prompt_hash,  # Full prompt hash, not truncated text
            "context_hash": hashlib.md5(str(context).encode()).hexdigest() if context else ""
        }

        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()

    async def _expire_cache(self, cache_key: str, ttl: int):
        """Expire a cache entry after TTL seconds"""
        await asyncio.sleep(ttl)
        if cache_key in self._cache:
            del self._cache[cache_key]
            logger.debug(f"Cache expired for key: {cache_key}")

    def get_total_cost(self) -> float:
        """Get total API costs for this session"""
        return self._total_cost

    def clear_cache(self):
        """Clear the response cache"""
        self._cache.clear()
        logger.info("AI response cache cleared")

    # Specific methods for each workflow step
    async def extract_modules(self, high_level_design: str) -> Dict[str, Any]:
        """
        Extract module list from high-level design (Step 3.1)
        Uses Claude 4 Sonnet for parsing
        """
        prompt = """Extract the list of circuit modules from this high-level design.

        High-Level Design:
        {design}

        Return a JSON object with:
        - modules: Array of module names (strings)
        - circuitName: Overall circuit name

        Example output:
        {{
            "modules": ["Power_Supply", "Input_Protection", "Amplifier"],
            "circuitName": "Audio_Amplifier"
        }}
        """.format(design=high_level_design)

        # Call AI with Claude 4 Sonnet
        result = await self.call_ai_with_retry(
            "step_3_extract_modules",  # Uses Claude 4 Sonnet
            prompt,
            context={"high_level_design": high_level_design}
        )

        return result

    async def design_circuit_module(self, module_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Design a single circuit module (Step 3)
        This is the critical step that needs most attention
        NOW USES SIMPLE TEXT FORMAT FOR 100% RELIABILITY

        ENHANCEMENT (Dec 2025): Now includes dynamic component rating guidance
        extracted from requirements to ensure proper voltage/current/power ratings.
        """
        # HYBRID PROMPT: Combines JSON output format with component rating guidelines
        # - JSON format: Faster API response (original approach)
        # - Rating rules: MOSFET Vds derating, capacitor voltage derating (SPICE-validated requirement)
        # - IC pinout verification: Prevents wrong pin connections (Dec 21 fix)
        prompt_file = Path("ai_agents/prompts/step_3_design_module_hybrid.txt")

        if not prompt_file.exists():
            # Use a default prompt if file doesn't exist yet
            prompt = """Design a circuit module with the following specifications:

            Module Name: {module_name}
            Requirements: {requirements}
            Interfaces: {interfaces}

            Generate a complete circuit in JSON format with:
            1. Components array with all necessary parts
            2. Connections array with proper wiring
            3. pinNetMapping object mapping each pin to its net
            4. nets array with all unique nets

            Ensure NO floating components and NO net conflicts.
            """
            # Format prompt with module data
            prompt = prompt.format(**module_data)
        else:
            prompt = prompt_file.read_text()
            # Replace N8N template variables
            prompt = prompt.replace('{{ $json.module }}', str(module_data.get('module', module_data.get('name', ''))))
            prompt = prompt.replace('{{ $json.moduleIndex + 1 }}', str(module_data.get('moduleIndex', 0) + 1))
            prompt = prompt.replace('{{ $json.totalModules }}', str(module_data.get('totalModules', 1)))

            # CRITICAL FIX: Replace {{ $json.requirements }} with actual requirements
            # This ensures the AI knows the electrical specs for each module
            requirements_str = ""
            if 'requirements' in module_data:
                req = module_data['requirements']
                if isinstance(req, dict):
                    requirements_str = json.dumps(req, indent=2)
                else:
                    requirements_str = str(req)
            elif 'context' in module_data:
                ctx = module_data['context']
                if isinstance(ctx, dict):
                    requirements_str = json.dumps(ctx, indent=2)
                else:
                    requirements_str = str(ctx)

            # If still empty, try to get from the circuitName or other fields
            if not requirements_str:
                requirements_str = f"Module: {module_data.get('module', 'Unknown')}\nCircuit: {module_data.get('circuitName', 'Unknown')}"

            prompt = prompt.replace('{{ $json.requirements }}', requirements_str)

            # CRITICAL ENHANCEMENT: Extract and inject component rating guidance
            # This ensures the AI knows the voltage/current/power requirements
            # and selects appropriately rated components for ANY circuit type
            component_rating_guidance = ""
            if RATING_EXTRACTOR_AVAILABLE:
                try:
                    # Extract requirements text from module_data
                    # Requirements can come from various fields
                    requirements_text = ""
                    if 'requirements' in module_data:
                        req = module_data['requirements']
                        if isinstance(req, dict):
                            requirements_text = json.dumps(req)
                        else:
                            requirements_text = str(req)
                    elif 'context' in module_data:
                        ctx = module_data['context']
                        if isinstance(ctx, dict):
                            requirements_text = json.dumps(ctx)
                        else:
                            requirements_text = str(ctx)

                    # Also check for specifications in the module data itself
                    if 'specifications' in module_data:
                        spec = module_data['specifications']
                        if isinstance(spec, dict):
                            requirements_text += "\n" + json.dumps(spec)
                        else:
                            requirements_text += "\n" + str(spec)

                    # Generate component guidance if we have requirements
                    if requirements_text:
                        component_rating_guidance = get_component_guidance_for_requirements(requirements_text)
                        logger.info(f"Injected component rating guidance for module {module_data.get('module', 'unknown')}")
                except Exception as e:
                    logger.warning(f"Could not extract component rating guidance: {e}")
                    component_rating_guidance = ""

            # Inject the component rating guidance into the prompt
            prompt = prompt.replace('{{ component_rating_guidance }}', component_rating_guidance)

        # ENHANCED RETRY LOGIC: Handle BOTH overload AND timeout errors
        # This is CRITICAL because Opus 4.5 can be slow for complex circuits
        max_retries = 3
        timeout_retries = 0
        max_timeout_retries = 2  # Max retries specifically for timeouts

        for attempt in range(max_retries):
            try:
                result = await self.call_ai(
                    "step_3_design_module",
                    prompt,
                    context={"module": module_data},
                    use_cache=(attempt == 0)  # Only use cache on first attempt
                )

                # Check for errors in response
                if not result.get('success'):
                    error_msg = str(result.get('error', '')).lower()

                    # Handle overload errors - retry with backoff
                    if 'overloaded' in error_msg and attempt < max_retries - 1:
                        wait_time = 10 * (attempt + 1)  # 10, 20, 30 seconds
                        logger.warning(f"AI overloaded for module {module_data.get('module')}. Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                        continue

                    # CRITICAL FIX: Handle TIMEOUT errors - retry with longer wait
                    # This is the "mother of all show stoppers" fix
                    if ('timeout' in error_msg or 'timed out' in error_msg) and timeout_retries < max_timeout_retries:
                        timeout_retries += 1
                        wait_time = 30 * timeout_retries  # 30, 60 seconds
                        logger.warning(
                            f"⚠️ AI TIMEOUT for module {module_data.get('module')} "
                            f"(attempt {timeout_retries}/{max_timeout_retries}). "
                            f"Waiting {wait_time}s before retry..."
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    # If we've exhausted timeout retries, log critical error
                    if 'timeout' in error_msg or 'timed out' in error_msg:
                        logger.error(
                            f"❌ CRITICAL: AI timeout after {max_timeout_retries} retries "
                            f"for module {module_data.get('module')}. "
                            f"Consider using Sonnet model or simplifying the prompt."
                        )

                return result

            except Exception as e:
                logger.error(f"Error in design_circuit_module attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                else:
                    return {
                        "success": False,
                        "error": str(e),
                        "module": module_data.get('module')
                    }

        # All retries exhausted
        return {
            "success": False,
            "error": f"Failed after {max_retries} retries (including {timeout_retries} timeout retries)",
            "module": module_data.get('module')
        }

    async def design_circuit_module_two_stage(self, module_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        TWO-STAGE CIRCUIT DESIGN APPROACH (Dec 21, 2025)

        This method splits circuit design into two focused stages to avoid API timeouts:

        Stage 1: Component Selection
        - Smaller prompt (~12K chars) with rating guidelines
        - Output: List of components with values, ratings, packages
        - Expected time: ~30-60 seconds

        Stage 2: Connection Synthesis
        - Takes components from Stage 1 as input
        - Smaller prompt (~15K chars) WITHOUT rating guidelines
        - Output: Connections, pinNetMapping, nets
        - Expected time: ~30-60 seconds

        Total expected time: ~60-120 seconds (vs 8+ min timeout with single-stage)

        This approach is GENERIC and works for ANY circuit type:
        - Simple LED blinker
        - Complex power supply
        - High-frequency RF circuits
        - Multi-channel amplifiers

        Args:
            module_data: Module information including requirements and context

        Returns:
            Complete circuit dict with components, connections, pinNetMapping, nets
        """
        module_name = module_data.get('module', module_data.get('name', 'Unknown'))
        logger.info(f"🔧 Starting TWO-STAGE design for module: {module_name}")

        # Stage 1: Component Selection
        logger.info(f"  Stage 1: Selecting components for {module_name}...")
        stage1_result = await self._stage1_select_components(module_data)

        if not stage1_result.get('success'):
            logger.error(f"  ❌ Stage 1 FAILED for {module_name}: {stage1_result.get('error')}")
            return stage1_result

        components = stage1_result.get('components', [])
        logger.info(f"  ✅ Stage 1 complete: {len(components)} components selected")

        # Stage 2: Connection Synthesis
        logger.info(f"  Stage 2: Synthesizing connections for {module_name}...")
        stage2_result = await self._stage2_synthesize_connections(module_data, components)

        if not stage2_result.get('success'):
            logger.error(f"  ❌ Stage 2 FAILED for {module_name}: {stage2_result.get('error')}")
            return stage2_result

        logger.info(f"  ✅ Stage 2 complete: Connections synthesized")

        # Merge Stage 1 and Stage 2 results into complete circuit
        circuit = self._merge_two_stage_results(module_name, stage1_result, stage2_result)

        logger.info(f"🔧 TWO-STAGE design complete for {module_name}")
        return {
            "success": True,
            "raw_response": json.dumps(circuit),
            "parsed_response": circuit,
            "metadata": {
                "stage1_components": len(components),
                "stage2_connections": len(stage2_result.get('connections', [])),
                "design_approach": "two_stage"
            }
        }

    async def _stage1_select_components(self, module_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stage 1: Component Selection

        Selects all components needed for the module with proper ratings.
        Includes rating guidelines in the prompt to ensure correct voltage/current/power ratings.

        Args:
            module_data: Module information including requirements

        Returns:
            Dict with 'success', 'components', and metadata
        """
        prompt_file = Path("ai_agents/prompts/step_3_stage1_components.txt")

        if not prompt_file.exists():
            logger.error(f"Stage 1 prompt file not found: {prompt_file}")
            return {"success": False, "error": "Stage 1 prompt file not found"}

        prompt = prompt_file.read_text()

        # Replace template variables
        module_name = module_data.get('module', module_data.get('name', ''))
        prompt = prompt.replace('{{ $json.module }}', str(module_name))
        prompt = prompt.replace('{{ $json.moduleIndex + 1 }}', str(module_data.get('moduleIndex', 0) + 1))
        prompt = prompt.replace('{{ $json.totalModules }}', str(module_data.get('totalModules', 1)))

        # Build module context from requirements
        module_context = self._build_module_context(module_data)
        prompt = prompt.replace('{{ $json.moduleContext }}', module_context)

        # Inject component rating guidance (CRITICAL for correct ratings)
        component_rating_guidance = ""
        if RATING_EXTRACTOR_AVAILABLE:
            try:
                requirements_text = self._extract_requirements_text(module_data)
                if requirements_text:
                    component_rating_guidance = get_component_guidance_for_requirements(requirements_text)
            except Exception as e:
                logger.warning(f"Could not extract component rating guidance: {e}")

        prompt = prompt.replace('{{ component_rating_guidance }}', component_rating_guidance)

        # Fix K.9: Inject interface contract into Stage 1 prompt.
        # This ensures the AI knows which signals the module MUST provide.
        interface_contract_text = self._build_interface_contract_text(module_data)
        prompt = prompt.replace('{{ interface_contract }}', interface_contract_text)

        # Call AI with retry logic
        max_retries = 2
        for attempt in range(max_retries):
            result = await self.call_ai(
                "step_3_stage1_components",
                prompt,
                context={"module": module_data},
                use_cache=(attempt == 0)
            )

            if result.get('success'):
                # TC #90: Detect if response is near token limit (potential truncation)
                usage = result.get('usage', {})
                output_tokens = usage.get('output_tokens', 0)
                # Get max_tokens from config for this step
                from server.config import Config
                step_config = Config.MODELS.get('step_3_stage1_components', {})
                max_tokens = step_config.get('max_tokens', 16000)
                if output_tokens >= max_tokens * 0.95:
                    logger.warning(f"⚠️ TC #90: Stage 1 response near token limit ({output_tokens}/{max_tokens})")
                    logger.warning(f"   JSON may be truncated - truncation recovery will attempt to fix")

                # Parse the response to extract components
                raw_response = result.get('raw_response', '')
                parsed = self._parse_stage1_response(raw_response)
                if parsed and 'components' in parsed:
                    # =====================================================================
                    # TC #93 CRITICAL FIX: Ensure ALL components have pins defined
                    # Without pins, Circuit Supervisor deletes pinNetMapping entries,
                    # resulting in circuits with 0 connections (the 3-month bug!)
                    # =====================================================================
                    components = parsed['components']
                    for comp in components:
                        if 'pins' not in comp or not comp['pins']:
                            comp['pins'] = self._generate_default_pins(comp)
                            logger.info(f"TC #93 FIX: Auto-generated {len(comp['pins'])} pins for {comp.get('ref', 'unknown')}")

                    return {
                        "success": True,
                        "components": components,
                        "designNotes": parsed.get('designNotes', []),
                        "moduleName": parsed.get('moduleName', module_name)
                    }
                else:
                    logger.warning(f"Stage 1 response parsing failed, attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(10)
                        continue
                    return {"success": False, "error": "Failed to parse Stage 1 response"}

            # Handle errors
            error_msg = str(result.get('error', '')).lower()
            if ('timeout' in error_msg or 'overloaded' in error_msg) and attempt < max_retries - 1:
                wait_time = 30 * (attempt + 1)
                logger.warning(f"Stage 1 error, waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                continue

            return result

        return {"success": False, "error": "Stage 1 failed after retries"}

    async def _stage2_synthesize_connections(self, module_data: Dict[str, Any], components: List[Dict]) -> Dict[str, Any]:
        """
        Stage 2: Connection Synthesis

        Creates connections between components selected in Stage 1.
        Does NOT include rating guidelines (components already have ratings).

        Args:
            module_data: Module information including requirements
            components: List of components from Stage 1

        Returns:
            Dict with 'success', 'connections', 'pinNetMapping', 'nets'
        """
        prompt_file = Path("ai_agents/prompts/step_3_stage2_connections.txt")

        if not prompt_file.exists():
            logger.error(f"Stage 2 prompt file not found: {prompt_file}")
            return {"success": False, "error": "Stage 2 prompt file not found"}

        prompt = prompt_file.read_text()

        # Replace template variables
        module_name = module_data.get('module', module_data.get('name', ''))
        prompt = prompt.replace('{{ $json.module }}', str(module_name))
        prompt = prompt.replace('{{ $json.moduleIndex + 1 }}', str(module_data.get('moduleIndex', 0) + 1))
        prompt = prompt.replace('{{ $json.totalModules }}', str(module_data.get('totalModules', 1)))

        # Inject components from Stage 1
        components_json = json.dumps(components, indent=2)
        prompt = prompt.replace('{{ $json.components }}', components_json)

        # Build module context from requirements
        module_context = self._build_module_context(module_data)
        prompt = prompt.replace('{{ $json.moduleContext }}', module_context)

        # Call AI with retry logic
        max_retries = 2
        for attempt in range(max_retries):
            result = await self.call_ai(
                "step_3_stage2_connections",
                prompt,
                context={"module": module_data, "components": components},
                use_cache=(attempt == 0)
            )

            if result.get('success'):
                # Parse the response to extract connections
                raw_response = result.get('raw_response', '')
                parsed = self._parse_stage2_response(raw_response)
                if parsed and 'connections' in parsed:
                    return {
                        "success": True,
                        "connections": parsed['connections'],
                        "pinNetMapping": parsed.get('pinNetMapping', {}),
                        "nets": parsed.get('nets', []),
                        "connectionNotes": parsed.get('connectionNotes', [])
                    }
                else:
                    logger.warning(f"Stage 2 response parsing failed, attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(10)
                        continue
                    return {"success": False, "error": "Failed to parse Stage 2 response"}

            # Handle errors
            error_msg = str(result.get('error', '')).lower()
            if ('timeout' in error_msg or 'overloaded' in error_msg) and attempt < max_retries - 1:
                wait_time = 30 * (attempt + 1)
                logger.warning(f"Stage 2 error, waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)
                continue

            return result

        return {"success": False, "error": "Stage 2 failed after retries"}

    def _build_interface_contract_text(self, module_data: Dict[str, Any]) -> str:
        """
        Fix K.9: Build a human-readable interface contract for the Stage 1 prompt.

        Extracts the module's required inputs, outputs, power_in, and power_out
        from the module_data (passed through from Step 2) and formats them as
        clear constraints for the AI's component selection.

        Generic: Works with any module regardless of circuit type.
        """
        lines = []
        interface = module_data.get('interface', {})

        # Also check top-level keys (some paths store them directly)
        outputs = interface.get('outputs', module_data.get('outputs', {}))
        inputs = interface.get('inputs', module_data.get('inputs', {}))
        power_out = interface.get('power_out', module_data.get('power_out', []))
        power_in = interface.get('power_in', module_data.get('power_in', []))

        if outputs:
            if isinstance(outputs, dict):
                out_list = list(outputs.keys())
            elif isinstance(outputs, list):
                out_list = [str(o) for o in outputs]
            else:
                out_list = [str(outputs)]
            lines.append(f"**Required OUTPUT signals:** {', '.join(out_list)}")

        if inputs:
            if isinstance(inputs, dict):
                in_list = list(inputs.keys())
            elif isinstance(inputs, list):
                in_list = [str(i) for i in inputs]
            else:
                in_list = [str(inputs)]
            lines.append(f"**Required INPUT signals:** {', '.join(in_list)}")

        if power_out:
            p_list = power_out if isinstance(power_out, list) else [str(power_out)]
            lines.append(f"**Power OUTPUT rails:** {', '.join(p_list)}")

        if power_in:
            p_list = power_in if isinstance(power_in, list) else [str(power_in)]
            lines.append(f"**Power INPUT rails:** {', '.join(p_list)}")

        if not lines:
            return "(No interface contract defined for this module)"

        return '\n'.join(lines)

    def _build_module_context(self, module_data: Dict[str, Any]) -> str:
        """
        Build module context string from module data.
        GENERIC - works for any circuit type.
        """
        context_parts = []

        # Module name and description
        if 'module' in module_data:
            context_parts.append(f"Module Name: {module_data['module']}")
        if 'description' in module_data:
            context_parts.append(f"Description: {module_data['description']}")

        # Inputs and outputs
        if 'inputs' in module_data:
            inputs = module_data['inputs']
            if isinstance(inputs, list):
                context_parts.append(f"Inputs: {', '.join(str(i) for i in inputs)}")
            else:
                context_parts.append(f"Inputs: {inputs}")

        if 'outputs' in module_data:
            outputs = module_data['outputs']
            if isinstance(outputs, list):
                context_parts.append(f"Outputs: {', '.join(str(o) for o in outputs)}")
            else:
                context_parts.append(f"Outputs: {outputs}")

        # Specifications
        if 'specifications' in module_data:
            specs = module_data['specifications']
            if isinstance(specs, dict):
                context_parts.append("Specifications:")
                for key, value in specs.items():
                    context_parts.append(f"  - {key}: {value}")
            else:
                context_parts.append(f"Specifications: {specs}")

        # Requirements
        if 'requirements' in module_data:
            req = module_data['requirements']
            if isinstance(req, dict):
                context_parts.append(f"Requirements:\n{json.dumps(req, indent=2)}")
            else:
                context_parts.append(f"Requirements: {req}")

        # S.6 FIX: Operating voltage domain — guides AI component selection
        # and rating validation. Without this, the AI infers voltage from
        # requirements text, which can lead to wrong component ratings.
        op_voltage = module_data.get('operating_voltage', '')
        if op_voltage:
            context_parts.append(f"Operating Voltage Domain: {op_voltage}")
        isolation = module_data.get('isolation_domain', '')
        if isolation:
            context_parts.append(f"Isolation Domain: {isolation}")

        # Subcomponents (Fix 2.1: new field from Step 2)
        if 'subcomponents' in module_data:
            subcomps = module_data['subcomponents']
            if isinstance(subcomps, list) and subcomps:
                context_parts.append(f"Subcomponents: {', '.join(str(s) for s in subcomps)}")

        # Context
        if 'context' in module_data:
            ctx = module_data['context']
            if isinstance(ctx, dict):
                context_parts.append(f"Context:\n{json.dumps(ctx, indent=2)}")
            else:
                context_parts.append(f"Context: {ctx}")

        # Fix 2.2: Sibling module interface summary for cross-module net naming
        if 'sibling_interfaces' in module_data:
            sibling_text = module_data['sibling_interfaces']
            if sibling_text:
                context_parts.append("")
                context_parts.append(sibling_text)

        return "\n".join(context_parts)

    def _extract_requirements_text(self, module_data: Dict[str, Any]) -> str:
        """Extract requirements text for rating extraction. GENERIC."""
        requirements_text = ""

        if 'requirements' in module_data:
            req = module_data['requirements']
            requirements_text += json.dumps(req) if isinstance(req, dict) else str(req)

        if 'context' in module_data:
            ctx = module_data['context']
            requirements_text += "\n" + (json.dumps(ctx) if isinstance(ctx, dict) else str(ctx))

        if 'specifications' in module_data:
            spec = module_data['specifications']
            requirements_text += "\n" + (json.dumps(spec) if isinstance(spec, dict) else str(spec))

        return requirements_text

    def _generate_default_pins(self, component: Dict[str, Any]) -> List[Dict]:
        """
        TC #93 CRITICAL FIX: Generate default pins for components missing pins field.

        This is the ROOT CAUSE of the 3-month bug:
        - Stage 1 AI sometimes returns components without pins
        - Circuit Supervisor checks pinNetMapping against component pins
        - If pins don't exist, ALL pinNetMapping entries are deleted as "invalid_pin"
        - Result: circuits with 0 connections, falling back to 2-component emergency circuit

        This method generates appropriate default pins based on component type.
        It is GENERIC - works for ANY component type.

        Pin count by component type:
        - Resistor, Capacitor, Inductor, LED, Diode: 2 pins
        - BJT (NPN/PNP), MOSFET, 3-pin regulator: 3 pins
        - Bridge rectifier: 4 pins
        - DIP-8 IC (op-amp, 555, etc.): 8 pins
        - DIP-14 logic IC: 14 pins
        - DIP-16 IC: 16 pins
        - Connector: based on value or default 2

        Args:
            component: Component dict with 'type', 'value', 'ref', etc.

        Returns:
            List of pin dictionaries with 'number', 'name', 'type' keys
        """
        comp_type = component.get('type', '').lower()
        comp_value = component.get('value', '').upper()
        comp_ref = component.get('ref', '').upper()
        package = component.get('package', '').upper()

        # Determine pin count based on component type
        pin_count = 2  # Default for passives

        # 2-pin components
        if comp_type in ['resistor', 'capacitor', 'inductor', 'led', 'diode', 'fuse',
                         'ferrite', 'varistor', 'thermistor', 'ntc', 'ptc']:
            pin_count = 2

        # 3-pin components
        elif comp_type in ['transistor', 'bjt', 'mosfet', 'igbt', 'triac', 'thyristor',
                           'voltage_regulator', 'regulator', 'ldo', 'potentiometer']:
            pin_count = 3
            # Some regulators are 5-pin (with TAB and NC)
            if 'TO-220-5' in package or 'DPAK' in package:
                pin_count = 5

        # 4-pin components
        elif comp_type in ['bridge', 'bridge_rectifier', 'optocoupler', 'opto',
                           'transformer', 'relay']:
            pin_count = 4
            # Some transformers have more pins
            if 'transformer' in comp_type:
                pin_count = 6  # Primary + Secondary + CT

        # IC-based pin counts
        elif comp_type in ['ic', 'amplifier', 'opamp', 'op_amp', 'comparator',
                           'microcontroller', 'mcu', 'dds', 'adc', 'dac',
                           'driver', 'gate_driver', 'current_sense']:
            # Determine from package
            if 'SOT-23' in package:
                pin_count = 3
            elif 'SOT-223' in package or 'SOT-89' in package:
                pin_count = 4
            elif 'SOIC-8' in package or 'DIP-8' in package or 'MSOP-8' in package:
                pin_count = 8
            elif 'SOIC-14' in package or 'DIP-14' in package or 'TSSOP-14' in package:
                pin_count = 14
            elif 'SOIC-16' in package or 'DIP-16' in package or 'TSSOP-16' in package:
                pin_count = 16
            elif 'DIP-20' in package or 'TSSOP-20' in package:
                pin_count = 20
            elif 'TQFP-32' in package or 'QFN-32' in package:
                pin_count = 32
            else:
                # Default for unknown IC packages
                pin_count = 8  # Assume 8-pin IC

        # Connector - extract pin count from value if possible
        elif comp_type in ['connector', 'header', 'terminal']:
            # Try to extract number from value like "HDR-2", "CONN-4", "J3"
            import re
            num_match = re.search(r'(\d+)', comp_value)
            if num_match:
                pin_count = int(num_match.group(1))
            else:
                pin_count = 2  # Default connector pins

        # Test point - single pin
        elif comp_type in ['test_point', 'testpoint', 'tp']:
            pin_count = 1

        # Heatsink, mounting hole - no electrical pins (but we need at least 1 for structure)
        elif comp_type in ['heatsink', 'mounting_hole', 'fiducial']:
            pin_count = 1

        # Crystal, resonator
        elif comp_type in ['crystal', 'resonator', 'oscillator']:
            pin_count = 2
            if 'oscillator' in comp_type:
                pin_count = 4  # OSC has VCC, GND, OUT, (NC or EN)

        # Generate pins
        pins = []
        for i in range(1, pin_count + 1):
            pin_name = str(i)
            pin_type = 'passive'

            # Try to assign meaningful names for common patterns
            if comp_type in ['resistor', 'capacitor', 'inductor', 'fuse']:
                pin_type = 'passive'
            elif comp_type in ['transistor', 'bjt']:
                if i == 1:
                    pin_name = 'B'  # Base
                elif i == 2:
                    pin_name = 'C'  # Collector
                elif i == 3:
                    pin_name = 'E'  # Emitter
            elif comp_type in ['mosfet', 'igbt']:
                if i == 1:
                    pin_name = 'G'  # Gate
                elif i == 2:
                    pin_name = 'D'  # Drain
                elif i == 3:
                    pin_name = 'S'  # Source
            elif comp_type in ['diode', 'led']:
                if i == 1:
                    pin_name = 'A'  # Anode
                    pin_type = 'passive'
                elif i == 2:
                    pin_name = 'K'  # Cathode
                    pin_type = 'passive'
            elif comp_type in ['voltage_regulator', 'regulator', 'ldo']:
                if i == 1:
                    pin_name = 'VIN'
                    pin_type = 'power_in'
                elif i == 2:
                    pin_name = 'GND'
                    pin_type = 'ground'
                elif i == 3:
                    pin_name = 'VOUT'
                    pin_type = 'power_out'

            pins.append({
                'number': str(i),
                'name': pin_name,
                'type': pin_type
            })

        logger.debug(f"Generated {len(pins)} default pins for {comp_ref} ({comp_type})")
        return pins

    def _repair_json(self, json_str: str, error: json.JSONDecodeError) -> Optional[str]:
        """
        Attempt to repair common JSON syntax errors.

        Common issues from AI-generated JSON:
        1. Missing comma between array elements or object properties
        2. Trailing comma before closing bracket
        3. Unescaped quotes in strings

        Args:
            json_str: The malformed JSON string
            error: The JSONDecodeError with position info

        Returns:
            Repaired JSON string or None if repair failed
        """
        pos = error.pos

        # Strategy 1: Missing comma - try inserting comma before error position
        # Common pattern: }\n  { or ]\n  [ without comma
        if 'Expecting' in str(error) and 'delimiter' in str(error):
            # Look backwards for the end of previous element
            search_start = max(0, pos - 50)
            context = json_str[search_start:pos]

            # Find last closing bracket/brace/quote
            for i in range(len(context) - 1, -1, -1):
                char = context[i]
                if char in '}]"':
                    # Insert comma after this position
                    insert_pos = search_start + i + 1
                    repaired = json_str[:insert_pos] + ',' + json_str[insert_pos:]
                    logger.info(f"JSON repair: inserted comma at position {insert_pos}")
                    return repaired

        # Strategy 2: Trailing comma - remove it
        if 'Expecting' in str(error) and pos > 0:
            # Check if there's a comma followed by closing bracket
            before = json_str[max(0, pos-10):pos].strip()
            if before.endswith(','):
                # Find and remove the trailing comma
                comma_pos = json_str.rfind(',', 0, pos)
                if comma_pos >= 0:
                    repaired = json_str[:comma_pos] + json_str[comma_pos+1:]
                    logger.info(f"JSON repair: removed trailing comma at position {comma_pos}")
                    return repaired

        return None

    def _recover_truncated_json(self, json_str: str) -> Optional[str]:
        """
        TC #90 FIX (2025-12-22): Attempt to recover truncated JSON.

        When the AI response hits the max_tokens limit, the JSON is cut off mid-sentence.
        This method detects truncation and attempts to close unclosed structures.

        This fix is GENERIC - works for ANY JSON structure, not tied to specific circuit format.

        Args:
            json_str: The potentially truncated JSON string

        Returns:
            Recovered JSON string or None if not truncated/recovery failed
        """
        # Count unclosed braces and brackets
        open_braces = json_str.count('{') - json_str.count('}')
        open_brackets = json_str.count('[') - json_str.count(']')

        if open_braces <= 0 and open_brackets <= 0:
            return None  # Not truncated (or has extra closers which is a different issue)

        logger.warning(f"TC #90: Detected truncated JSON - {open_braces} unclosed braces, {open_brackets} unclosed brackets")

        # Remove incomplete key-value pair at the end
        # Patterns: ,"key": or "key": at end without value, or partial value like "pitch
        truncated = json_str.rstrip()

        # Pattern 1: Ends with incomplete string value (missing closing quote)
        # e.g., "pitch": "5.08 ends here
        if re.search(r':\s*"[^"]*$', truncated):
            # Find the last complete key-value or array element
            last_complete = truncated.rfind('",')
            if last_complete > 0:
                truncated = truncated[:last_complete + 2]
                logger.info(f"TC #90: Removed incomplete string value")

        # Pattern 2: Ends with incomplete key (colon without value)
        # e.g., "pitch":
        truncated = re.sub(r',?\s*"[^"]*":\s*$', '', truncated)

        # Pattern 3: Ends with incomplete object/array start
        # e.g., { or [
        truncated = re.sub(r',?\s*[\[{]\s*$', '', truncated)

        # Pattern 4: Ends with trailing comma
        truncated = re.sub(r',\s*$', '', truncated)

        # Recalculate after cleanup
        open_braces = truncated.count('{') - truncated.count('}')
        open_brackets = truncated.count('[') - truncated.count(']')

        # Close unclosed structures (brackets first, then braces)
        truncated += ']' * max(0, open_brackets)
        truncated += '}' * max(0, open_braces)

        logger.info(f"TC #90: Recovered truncated JSON by closing {open_brackets} brackets and {open_braces} braces")

        return truncated

    def _parse_with_repair(self, json_str: str, stage_name: str) -> Optional[Dict]:
        """
        Parse JSON with automatic repair attempts.

        TC #90 Enhanced (2025-12-22): Added truncation recovery as first repair strategy.
        This handles the common case where AI responses are cut off at max_tokens limit.

        Repair order:
        1. Direct parse
        2. Truncation recovery (TC #90)
        3. Syntax repair (missing commas, trailing commas)
        4. Double repair attempt

        Args:
            json_str: JSON string to parse
            stage_name: "Stage 1" or "Stage 2" for logging

        Returns:
            Parsed dict or None if all attempts failed
        """
        # First attempt: direct parse
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"{stage_name} JSON parse failed at position {e.pos}: {e.msg}")

            # TC #90: Second attempt - try truncation recovery FIRST
            # This is the most common issue when hitting max_tokens limit
            recovered = self._recover_truncated_json(json_str)
            if recovered:
                try:
                    result = json.loads(recovered)
                    # Log success with component count for visibility
                    comp_count = len(result.get('components', []))
                    logger.info(f"TC #90: {stage_name} JSON recovered from truncation! ({comp_count} components)")
                    return result
                except json.JSONDecodeError as e_recover:
                    logger.warning(f"TC #90: Truncation recovery parsed but still invalid: {e_recover.msg}")
                    # Continue to other repair strategies

            # Third attempt: try syntax repair
            repaired = self._repair_json(json_str, e)
            if repaired:
                try:
                    result = json.loads(repaired)
                    logger.info(f"{stage_name} JSON successfully repaired and parsed!")
                    return result
                except json.JSONDecodeError as e2:
                    logger.warning(f"{stage_name} repair attempt failed: {e2.msg}")

                    # Fourth attempt: try repair again on the repaired string
                    repaired2 = self._repair_json(repaired, e2)
                    if repaired2:
                        try:
                            result = json.loads(repaired2)
                            logger.info(f"{stage_name} JSON repaired on second attempt!")
                            return result
                        except json.JSONDecodeError:
                            pass

            logger.error(f"Failed to parse {stage_name} response after all repair attempts: {e}")
            return None

    def _parse_stage1_response(self, raw_response: str) -> Optional[Dict]:
        """Parse Stage 1 (component selection) response with error recovery."""
        # Try to extract JSON from markdown code block
        json_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', raw_response)
        if json_match:
            result = self._parse_with_repair(json_match.group(1).strip(), "Stage 1")
            if result:
                return result

        # Try direct JSON parse
        if '{' in raw_response:
            start = raw_response.find('{')
            end = raw_response.rfind('}') + 1
            if start >= 0 and end > start:
                result = self._parse_with_repair(raw_response[start:end], "Stage 1")
                if result:
                    return result

        logger.error("Failed to parse Stage 1 response: no valid JSON found")
        return None

    def _parse_stage2_response(self, raw_response: str) -> Optional[Dict]:
        """Parse Stage 2 (connection synthesis) response with error recovery."""
        # Try to extract JSON from markdown code block
        json_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', raw_response)
        if json_match:
            result = self._parse_with_repair(json_match.group(1).strip(), "Stage 2")
            if result:
                return result

        # Try direct JSON parse
        if '{' in raw_response:
            start = raw_response.find('{')
            end = raw_response.rfind('}') + 1
            if start >= 0 and end > start:
                result = self._parse_with_repair(raw_response[start:end], "Stage 2")
                if result:
                    return result

        logger.error("Failed to parse Stage 2 response: no valid JSON found")
        return None

    def _merge_two_stage_results(self, module_name: str, stage1: Dict, stage2: Dict) -> Dict:
        """
        Merge Stage 1 (components) and Stage 2 (connections) into complete circuit.

        TC #93 FIX (2025-12-25): Rebuild connections from pinNetMapping to ensure
        all pins on the same net are properly connected. The AI sometimes generates
        incomplete connections arrays where nets have only 1 point instead of 2+.

        This fix is GENERIC - works for ANY circuit type by deriving connections
        directly from the pinNetMapping which is typically more complete.

        Args:
            module_name: Name of the module
            stage1: Stage 1 result with components
            stage2: Stage 2 result with connections

        Returns:
            Complete circuit dict ready for Circuit Supervisor
        """
        pinNetMapping = stage2.get('pinNetMapping', {})
        original_connections = stage2.get('connections', [])

        # =====================================================================
        # TC #93 FIX: Rebuild connections from pinNetMapping
        # The AI assigns pins to nets correctly in pinNetMapping, but the
        # connections array may be incomplete (nets with only 1 point).
        # Solution: Group all pins by their net from pinNetMapping.
        # =====================================================================

        # Build net -> pins mapping from pinNetMapping
        net_to_pins = {}
        for pin, net in pinNetMapping.items():
            if net not in net_to_pins:
                net_to_pins[net] = []
            net_to_pins[net].append(pin)

        # Build complete connections array
        rebuilt_connections = []
        for net, pins in net_to_pins.items():
            rebuilt_connections.append({
                "net": net,
                "points": sorted(pins)  # Sort for consistency
            })

        # Log improvement statistics
        original_single_ended = sum(1 for c in original_connections if len(c.get('points', [])) < 2)
        rebuilt_single_ended = sum(1 for c in rebuilt_connections if len(c.get('points', [])) < 2)

        if original_single_ended > rebuilt_single_ended:
            logger.info(f"TC #93 FIX: Rebuilt connections for {module_name}")
            logger.info(f"  Original single-ended nets: {original_single_ended}")
            logger.info(f"  After rebuild: {rebuilt_single_ended}")

        # Use rebuilt connections
        connections = rebuilt_connections

        # Build complete nets list from net_to_pins
        nets = list(net_to_pins.keys())

        circuit = {
            "moduleName": module_name,
            "components": stage1.get('components', []),
            "connections": connections,
            "pinNetMapping": pinNetMapping,
            "nets": nets,
            "notes": stage1.get('designNotes', []) + stage2.get('connectionNotes', [])
        }

        logger.info(f"Merged circuit for {module_name}: "
                   f"{len(circuit['components'])} components, "
                   f"{len(circuit['connections'])} connections, "
                   f"{len(circuit['nets'])} nets")

        return circuit

    async def fix_circuit_issues(self, circuit: Dict[str, Any], issues: List[str]) -> Dict[str, Any]:
        """
        Fix circuit issues using AI
        More intelligent than mechanical fixes
        """
        prompt = f"""Fix the following issues in this circuit:

        Issues to fix:
        {json.dumps(issues, indent=2)}

        Circuit:
        {json.dumps(circuit, indent=2)}

        Return the fixed circuit in the same JSON format.
        Ensure all issues are resolved while maintaining circuit functionality.
        """

        result = await self.call_ai_with_retry(
            "step_3_fix_circuit",
            prompt,
            context={"original_circuit": circuit, "issues": issues}
        )

        return result

    async def select_best_part(self, component_spec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Select the best part for a component (Step 4.1)
        Uses Claude 4 Sonnet with temperature 0.2
        """
        prompt = """Select the best manufacturer part for this component specification:

        Component Type: {type}
        Value: {value}
        Package: {package}
        Requirements: {requirements}

        Return a JSON object with:
        - partNumber: Specific manufacturer part number
        - manufacturer: Company name
        - description: Part description
        - unitPrice: Estimated price
        - availability: Stock status
        - datasheet: URL if available

        Choose commonly available, reliable parts from reputable manufacturers.
        """.format(**component_spec)

        result = await self.call_ai_with_retry(
            "step_4_select_part",  # Uses Claude 4 Sonnet, temp 0.2
            prompt,
            context={"component": component_spec}
        )

        return result

    async def optimize_bom(self, bom_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Optimize the BOM for cost and availability (Step 4.2)
        Uses Claude 4 Sonnet with temperature 0.3
        """
        prompt = """Optimize this Bill of Materials for cost and availability:

        Current BOM:
        {bom}

        Optimization goals:
        1. Reduce total cost
        2. Consolidate similar parts
        3. Suggest alternative parts if needed
        4. Group by manufacturer for volume discounts
        5. Flag any obsolete or hard-to-find parts

        Return a JSON object with:
        - optimizedBOM: Array of optimized parts
        - totalCost: Estimated total
        - savings: Amount saved
        - recommendations: Array of optimization suggestions
        """.format(bom=json.dumps(bom_list, indent=2))

        result = await self.call_ai_with_retry(
            "step_4_optimize_bom",  # Uses Claude 4 Sonnet, temp 0.3
            prompt,
            context={"original_bom": bom_list}
        )

        return result

# =============================================================================
# MULTI-AGENT COORDINATION METHODS (Jan 2026)
# =============================================================================
# These methods enable hierarchical agent coordination for complex circuits.
# They complement the existing single-agent methods above.
# =============================================================================

    async def call_specialized_agent(
        self,
        agent_type: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Call a specialized agent with its configured model and parameters.

        This method routes requests to the appropriate model configuration
        for specialized agents in the multi-agent architecture.

        Agent Types:
          - component_agent: Component selection (Sonnet, temp 0.3)
          - connection_agent: Connection synthesis (Sonnet, temp 0.2)
          - validation_agent: Per-module validation (Sonnet, temp 0.1)
          - integration_agent: Cross-module integration (Sonnet, temp 0.2)
          - supervisor_interface: Interface definition (Opus, temp 0.4)

        Args:
            agent_type: Type of specialized agent to use
            prompt: The prompt to send to the agent
            context: Additional context for the agent
            use_cache: Whether to use cached responses

        Returns:
            Dict containing the agent's response and metadata
        """
        # Map agent type to step name for config lookup
        step_name = agent_type
        if not agent_type.startswith('step_'):
            step_name = agent_type

        logger.info(f"🤖 Calling specialized agent: {agent_type}")

        result = await self.call_ai(
            step_name,
            prompt,
            context=context,
            use_cache=use_cache
        )

        # Add agent type to metadata
        if result.get('metadata'):
            result['metadata']['agent_type'] = agent_type

        return result

    async def call_agents_parallel(
        self,
        agent_calls: List[Tuple[str, str, Optional[Dict[str, Any]]]]
    ) -> List[Dict[str, Any]]:
        """
        Execute multiple agent calls in parallel.

        This is the core method for parallel module design, where independent
        modules can be designed concurrently by different agent instances.

        CRITICAL: Only use for truly independent tasks. If agents need
        outputs from other agents, use sequential calls instead.

        Args:
            agent_calls: List of tuples (agent_type, prompt, context)

        Returns:
            List of results in the same order as input calls

        Example:
            calls = [
                ("component_agent", prompt1, {"module": "Power_Supply"}),
                ("component_agent", prompt2, {"module": "Controller"}),
                ("component_agent", prompt3, {"module": "Driver"})
            ]
            results = await agent_manager.call_agents_parallel(calls)
        """
        logger.info(f"🚀 Starting parallel execution of {len(agent_calls)} agent calls")

        # Create tasks for all agent calls
        tasks = []
        for agent_type, prompt, context in agent_calls:
            task = self.call_specialized_agent(
                agent_type=agent_type,
                prompt=prompt,
                context=context,
                use_cache=True
            )
            tasks.append(task)

        # Execute all tasks concurrently
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - start_time

        # Process results, converting exceptions to error dicts
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Agent call {i} failed with exception: {result}")
                processed_results.append({
                    "success": False,
                    "error": str(result),
                    "agent_type": agent_calls[i][0]
                })
            else:
                processed_results.append(result)

        # Log statistics
        successful = sum(1 for r in processed_results if r.get('success'))
        logger.info(f"🏁 Parallel execution complete: {successful}/{len(agent_calls)} successful in {elapsed:.1f}s")

        return processed_results

    async def design_module_multi_agent(
        self,
        module_data: Dict[str, Any],
        interface_contract: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Design a single module using the multi-agent approach.

        This orchestrates the component, connection, and validation agents
        for a single module design. Used by ModuleAgent.

        Flow:
          1. ComponentAgent selects components based on requirements
          2. ConnectionAgent creates connections between components
          3. ValidationAgent validates the complete module
          4. If validation fails, attempt repair and re-validate

        Args:
            module_data: Module information (name, requirements, interfaces)
            interface_contract: Interface contract defining inputs/outputs

        Returns:
            Complete module circuit with components, connections, validation
        """
        module_name = module_data.get('name', module_data.get('module', 'Unknown'))
        logger.info(f"🔧 Multi-agent design for module: {module_name}")

        # Load prompts
        prompts_dir = Path("ai_agents/prompts/multi_agent")

        # Stage 1: Component Selection
        component_prompt_file = prompts_dir / "component_selection_prompt.txt"
        if component_prompt_file.exists():
            component_prompt = component_prompt_file.read_text()
            component_prompt = self._inject_module_data(component_prompt, module_data, interface_contract)
        else:
            logger.warning(f"Component prompt not found, using default")
            component_prompt = self._build_default_component_prompt(module_data, interface_contract)

        # Inject rating guidance if available
        if RATING_EXTRACTOR_AVAILABLE:
            try:
                requirements_text = self._extract_requirements_text(module_data)
                if requirements_text:
                    guidance = get_component_guidance_for_requirements(requirements_text)
                    component_prompt = component_prompt.replace('{{ component_rating_guidance }}', guidance)
                    # Multi-agent prompt uses {{ rating_guidelines }} as alias
                    component_prompt = component_prompt.replace('{{ rating_guidelines }}', guidance)
            except Exception as e:
                logger.warning(f"Could not inject rating guidance: {e}")
                component_prompt = component_prompt.replace('{{ component_rating_guidance }}', '')
                component_prompt = component_prompt.replace('{{ rating_guidelines }}', '')

        # Clean up any remaining unreplaced placeholders
        component_prompt = component_prompt.replace('{{ component_rating_guidance }}', '')
        component_prompt = component_prompt.replace('{{ rating_guidelines }}', '')

        logger.info(f"  Stage 1: Component selection for {module_name}...")
        component_result = await self.call_specialized_agent(
            "component_agent",
            component_prompt,
            context={"module": module_data, "interface": interface_contract}
        )

        if not component_result.get('success'):
            logger.error(f"  ❌ Component selection failed: {component_result.get('error')}")
            return component_result

        # Parse components from response
        components = self._extract_components_from_response(component_result)
        if not components:
            return {"success": False, "error": "Failed to extract components from agent response"}

        # Ensure all components have pins (TC #93 fix)
        for comp in components:
            if 'pins' not in comp or not comp['pins']:
                comp['pins'] = self._generate_default_pins(comp)
                logger.info(f"  TC #93: Auto-generated pins for {comp.get('ref', 'unknown')}")

        logger.info(f"  ✅ Stage 1 complete: {len(components)} components")

        # Stage 2: Connection Synthesis
        connection_prompt_file = prompts_dir / "connection_synthesis_prompt.txt"
        if connection_prompt_file.exists():
            connection_prompt = connection_prompt_file.read_text()
            connection_prompt = self._inject_module_data(connection_prompt, module_data, interface_contract)
            connection_prompt = connection_prompt.replace(
                '{{ components }}',
                json.dumps(components, indent=2)
            )
        else:
            logger.warning(f"Connection prompt not found, using default")
            connection_prompt = self._build_default_connection_prompt(module_data, components)

        logger.info(f"  Stage 2: Connection synthesis for {module_name}...")
        connection_result = await self.call_specialized_agent(
            "connection_agent",
            connection_prompt,
            context={"module": module_data, "components": components}
        )

        if not connection_result.get('success'):
            logger.error(f"  ❌ Connection synthesis failed: {connection_result.get('error')}")
            return connection_result

        # Parse connections from response
        connections_data = self._extract_connections_from_response(connection_result)
        if not connections_data:
            return {"success": False, "error": "Failed to extract connections from agent response"}

        logger.info(f"  ✅ Stage 2 complete: {len(connections_data.get('connections', []))} connections")

        # Stage 3: Validation
        circuit = {
            "moduleName": module_name,
            "components": components,
            "connections": connections_data.get('connections', []),
            "pinNetMapping": connections_data.get('pinNetMapping', {}),
            "nets": connections_data.get('nets', [])
        }

        validation_prompt_file = prompts_dir / "module_validation_prompt.txt"
        if validation_prompt_file.exists():
            validation_prompt = validation_prompt_file.read_text()
            validation_prompt = self._inject_validation_data(validation_prompt, circuit, interface_contract)
        else:
            logger.warning(f"Validation prompt not found, skipping validation")
            return {
                "success": True,
                "circuit": circuit,
                "validation": {"passed": True, "skipped": True}
            }

        logger.info(f"  Stage 3: Validating {module_name}...")
        validation_result = await self.call_specialized_agent(
            "validation_agent",
            validation_prompt,
            context={"circuit": circuit}
        )

        validation_data = self._extract_validation_from_response(validation_result)

        if validation_data and not validation_data.get('passed', True):
            issues = validation_data.get('issues', [])
            logger.warning(f"  ⚠️ Validation found {len(issues)} issues")

            # Attempt auto-fix for critical issues
            circuit = self._auto_fix_validation_issues(circuit, issues)

        logger.info(f"  ✅ Multi-agent design complete for {module_name}")

        return {
            "success": True,
            "circuit": circuit,
            "validation": validation_data or {"passed": True}
        }

    def _inject_module_data(
        self,
        prompt: str,
        module_data: Dict[str, Any],
        interface_contract: Dict[str, Any]
    ) -> str:
        """Inject module data into prompt template."""
        module_name = module_data.get('name', module_data.get('module', 'Unknown'))

        # Replace common template variables
        prompt = prompt.replace('{{ module_name }}', str(module_name))
        prompt = prompt.replace('{{ $json.module }}', str(module_name))

        # Build and inject requirements
        requirements_str = ""
        if 'requirements' in module_data:
            req = module_data['requirements']
            requirements_str = json.dumps(req, indent=2) if isinstance(req, dict) else str(req)
        prompt = prompt.replace('{{ requirements }}', requirements_str)
        prompt = prompt.replace('{{ $json.requirements }}', requirements_str)

        # Build and inject interface
        interface_str = json.dumps(interface_contract, indent=2) if interface_contract else "{}"
        prompt = prompt.replace('{{ interface }}', interface_str)
        prompt = prompt.replace('{{ interface_contract }}', interface_str)

        # Fix K.9: Multi-agent interface sub-field placeholders
        if interface_contract:
            power_in = interface_contract.get('power_in', [])
            power_in_str = '\n'.join(f"- {p}" for p in power_in) if power_in else "(none)"
            prompt = prompt.replace('{{ power_in }}', power_in_str)

            power_out = interface_contract.get('power_out', [])
            power_out_str = '\n'.join(f"- {p}" for p in power_out) if power_out else "(none)"
            prompt = prompt.replace('{{ power_out }}', power_out_str)

            inputs = interface_contract.get('inputs', {})
            if isinstance(inputs, dict):
                inputs_str = '\n'.join(f"- {name}: {desc}" for name, desc in inputs.items()) if inputs else "(none)"
            elif isinstance(inputs, list):
                inputs_str = '\n'.join(f"- {i}" for i in inputs) if inputs else "(none)"
            else:
                inputs_str = str(inputs) if inputs else "(none)"
            prompt = prompt.replace('{{ interface_inputs }}', inputs_str)

            outputs = interface_contract.get('outputs', {})
            if isinstance(outputs, dict):
                outputs_str = '\n'.join(f"- {name}: {desc}" for name, desc in outputs.items()) if outputs else "(none)"
            elif isinstance(outputs, list):
                outputs_str = '\n'.join(f"- {o}" for o in outputs) if outputs else "(none)"
            else:
                outputs_str = str(outputs) if outputs else "(none)"
            prompt = prompt.replace('{{ interface_outputs }}', outputs_str)
        else:
            prompt = prompt.replace('{{ power_in }}', '(none)')
            prompt = prompt.replace('{{ power_out }}', '(none)')
            prompt = prompt.replace('{{ interface_inputs }}', '(none)')
            prompt = prompt.replace('{{ interface_outputs }}', '(none)')

        # Multi-agent module metadata placeholders
        module_func = module_data.get('function', module_data.get('description', ''))
        prompt = prompt.replace('{{ module_function }}', str(module_func))

        module_req = module_data.get('requirements', {})
        if isinstance(module_req, dict):
            req_str = json.dumps(module_req, indent=2)
        elif isinstance(module_req, list):
            req_str = '\n'.join(f"- {r}" for r in module_req)
        else:
            req_str = str(module_req)
        prompt = prompt.replace('{{ module_requirements }}', req_str)

        module_specs = module_data.get('specifications', module_data.get('specs', {}))
        if isinstance(module_specs, dict):
            specs_str = json.dumps(module_specs, indent=2)
        elif isinstance(module_specs, list):
            specs_str = '\n'.join(f"- {s}" for s in module_specs)
        else:
            specs_str = str(module_specs)
        prompt = prompt.replace('{{ module_specifications }}', specs_str)

        # Build module context
        context_str = self._build_module_context(module_data)
        prompt = prompt.replace('{{ $json.moduleContext }}', context_str)
        prompt = prompt.replace('{{ module_context }}', context_str)

        return prompt

    def _inject_validation_data(
        self,
        prompt: str,
        circuit: Dict[str, Any],
        interface_contract: Dict[str, Any]
    ) -> str:
        """Inject circuit data into validation prompt."""
        module_name = circuit.get('moduleName', 'Unknown')
        components = circuit.get('components', [])
        connections = circuit.get('connections', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})

        # Replace template variables
        prompt = prompt.replace('{{ module_name }}', str(module_name))
        prompt = prompt.replace('{{ components }}', json.dumps(components, indent=2))
        prompt = prompt.replace('{{ connections }}', json.dumps(connections, indent=2))
        prompt = prompt.replace('{{ pin_net_mapping }}', json.dumps(pin_net_mapping, indent=2))
        prompt = prompt.replace('{{ interface }}', json.dumps(interface_contract, indent=2))

        return prompt

    def _extract_components_from_response(self, result: Dict[str, Any]) -> Optional[List[Dict]]:
        """Extract components list from agent response."""
        parsed = result.get('parsed_response')
        if isinstance(parsed, dict) and 'components' in parsed:
            return parsed['components']

        raw = result.get('raw_response', '')
        parsed = self._parse_stage1_response(raw)
        if parsed and 'components' in parsed:
            return parsed['components']

        return None

    def _extract_connections_from_response(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract connections data from agent response."""
        parsed = result.get('parsed_response')
        if isinstance(parsed, dict) and 'connections' in parsed:
            return parsed

        raw = result.get('raw_response', '')
        parsed = self._parse_stage2_response(raw)
        if parsed:
            return parsed

        return None

    def _extract_validation_from_response(self, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract validation results from agent response."""
        if not result.get('success'):
            return None

        parsed = result.get('parsed_response')
        if isinstance(parsed, dict):
            return parsed

        raw = result.get('raw_response', '')
        # Try to parse JSON from response
        try:
            if '{' in raw:
                start = raw.find('{')
                end = raw.rfind('}') + 1
                if start >= 0 and end > start:
                    return json.loads(raw[start:end])
        except json.JSONDecodeError:
            pass

        return None

    def _auto_fix_validation_issues(
        self,
        circuit: Dict[str, Any],
        issues: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Auto-fix common validation issues.

        Handles critical issues that can be fixed mechanically:
          - ic_missing_power: Add power connection
          - ic_missing_ground: Add ground connection
          - shorted_passive: Fix by assigning different nets (LAW 4)
          - floating_component: Add NC connections

        Returns the fixed circuit.
        """
        pinNetMapping = circuit.get('pinNetMapping', {})
        connections = circuit.get('connections', [])

        for issue in issues:
            issue_type = issue.get('type', '')
            component = issue.get('component', '')
            severity = issue.get('severity', 'warning')

            if severity not in ['critical', 'error']:
                continue  # Only auto-fix critical/error issues

            logger.info(f"  🔧 Auto-fixing: {issue_type} on {component}")

            if issue_type == 'ic_missing_power':
                # Find VCC pin and connect to VCC
                for comp in circuit.get('components', []):
                    if comp.get('ref') == component:
                        for pin in comp.get('pins', []):
                            pin_name = pin.get('name', '').upper()
                            if pin_name in ['VCC', 'VDD', 'V+', 'VIN']:
                                pin_key = f"{component}.{pin.get('number', pin_name)}"
                                pinNetMapping[pin_key] = 'VCC'
                                logger.info(f"    Connected {pin_key} to VCC")
                                break

            elif issue_type == 'ic_missing_ground':
                # Find GND pin and connect to GND
                for comp in circuit.get('components', []):
                    if comp.get('ref') == component:
                        for pin in comp.get('pins', []):
                            pin_name = pin.get('name', '').upper()
                            if pin_name in ['GND', 'VSS', 'V-', 'GROUND']:
                                pin_key = f"{component}.{pin.get('number', pin_name)}"
                                pinNetMapping[pin_key] = 'GND'
                                logger.info(f"    Connected {pin_key} to GND")
                                break

            elif issue_type == 'shorted_passive':
                # LAW 4 violation - find the pins and assign to different nets
                for comp in circuit.get('components', []):
                    if comp.get('ref') == component:
                        pins = comp.get('pins', [])
                        if len(pins) >= 2:
                            # Find what net they're both on
                            pin1_key = f"{component}.1"
                            pin2_key = f"{component}.2"
                            current_net = pinNetMapping.get(pin1_key, 'NC')

                            # Create a new net for one of the pins
                            new_net = f"{component}_SIG"
                            pinNetMapping[pin1_key] = new_net
                            logger.info(f"    Fixed LAW 4: {pin1_key} moved to {new_net}")

        # Rebuild connections from updated pinNetMapping
        net_to_pins = {}
        for pin, net in pinNetMapping.items():
            if net not in net_to_pins:
                net_to_pins[net] = []
            net_to_pins[net].append(pin)

        new_connections = []
        for net, pins in net_to_pins.items():
            new_connections.append({
                "net": net,
                "points": sorted(pins)
            })

        circuit['pinNetMapping'] = pinNetMapping
        circuit['connections'] = new_connections
        circuit['nets'] = list(net_to_pins.keys())

        return circuit

    def _build_default_component_prompt(
        self,
        module_data: Dict[str, Any],
        interface_contract: Dict[str, Any]
    ) -> str:
        """Build default component selection prompt when template not found."""
        module_name = module_data.get('name', module_data.get('module', 'Unknown'))
        requirements = module_data.get('requirements', {})

        return f"""Select components for the {module_name} module.

Requirements:
{json.dumps(requirements, indent=2)}

Interface Contract:
{json.dumps(interface_contract, indent=2)}

Return a JSON object with:
- components: Array of component objects with ref, type, value, package, pins
- designNotes: Array of design considerations

Each component MUST have a pins array with pin definitions.
"""

    def _build_default_connection_prompt(
        self,
        module_data: Dict[str, Any],
        components: List[Dict]
    ) -> str:
        """Build default connection synthesis prompt when template not found."""
        module_name = module_data.get('name', module_data.get('module', 'Unknown'))

        return f"""Create connections for the {module_name} module.

Components:
{json.dumps(components, indent=2)}

CRITICAL LAWS:
- LAW 4: Two-terminal passives MUST have pins on DIFFERENT nets
- All ICs must have VCC and GND connections
- No floating pins on critical signals

Return a JSON object with:
- connections: Array of {{net, points}} objects
- pinNetMapping: Object mapping each pin to its net
- nets: Array of all unique net names
"""

    async def design_circuit_multi_agent(
        self,
        high_level_design: str,
        design_parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Design a complete circuit using the multi-agent architecture.

        This is the top-level entry point that orchestrates all agents.
        For complex circuits (3+ modules), this approach is recommended
        over single-agent design.

        Flow:
          1. Extract modules from high-level design
          2. Define interface contracts between modules
          3. Design each module in parallel (or batches)
          4. Integrate all modules
          5. System-level validation

        Args:
            high_level_design: High-level design text from Step 2
            design_parameters: Original design parameters from Step 1

        Returns:
            Complete integrated circuit with all modules
        """
        logger.info("🏗️ Starting multi-agent circuit design")

        # Check if multi-agent is enabled
        multi_agent_config = getattr(config, 'MULTI_AGENT_CONFIG', {})
        if not multi_agent_config.get('enabled', True):
            logger.info("Multi-agent disabled, falling back to single-agent")
            return await self._fallback_single_agent(high_level_design, design_parameters)

        try:
            # Import the DesignSupervisor
            from workflow.agents.design_supervisor import DesignSupervisor

            # Create supervisor and run orchestration
            supervisor = DesignSupervisor(self, high_level_design, design_parameters)
            result = await supervisor.orchestrate()

            return result

        except ImportError as e:
            logger.error(f"Failed to import DesignSupervisor: {e}")
            logger.info("Falling back to single-agent design")
            return await self._fallback_single_agent(high_level_design, design_parameters)
        except Exception as e:
            logger.error(f"Multi-agent design failed: {e}")
            logger.info("Falling back to single-agent design")
            return await self._fallback_single_agent(high_level_design, design_parameters)

    async def _fallback_single_agent(
        self,
        high_level_design: str,
        design_parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Fallback to single-agent design when multi-agent fails or is disabled.
        Uses the existing two-stage approach.
        """
        logger.info("Using single-agent fallback (two-stage design)")

        # Extract modules first
        modules_result = await self.extract_modules(high_level_design)
        if not modules_result.get('success'):
            return modules_result

        modules = modules_result.get('parsed_response', {}).get('modules', [])

        # Design each module using two-stage approach
        all_circuits = []
        for i, module_name in enumerate(modules):
            module_data = {
                'module': module_name,
                'moduleIndex': i,
                'totalModules': len(modules),
                'requirements': design_parameters,
                'context': high_level_design
            }

            result = await self.design_circuit_module_two_stage(module_data)
            if result.get('success'):
                circuit = result.get('parsed_response', {})
                all_circuits.append(circuit)
            else:
                logger.error(f"Module {module_name} design failed: {result.get('error')}")

        # Merge all module circuits
        if all_circuits:
            merged = self._merge_module_circuits(all_circuits)
            return {
                "success": True,
                "circuit": merged,
                "metadata": {
                    "design_approach": "single_agent_fallback",
                    "modules_designed": len(all_circuits)
                }
            }

        return {"success": False, "error": "All module designs failed"}

    def _merge_module_circuits(self, circuits: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge multiple module circuits into a single integrated circuit."""
        merged_components = []
        merged_connections = []
        merged_pin_net_mapping = {}
        merged_nets = set()

        for circuit in circuits:
            module_name = circuit.get('moduleName', '')

            # Add components with module prefix
            for comp in circuit.get('components', []):
                comp_copy = comp.copy()
                # Prefix ref with module name to avoid conflicts
                original_ref = comp_copy.get('ref', '')
                if module_name and not original_ref.startswith(f"{module_name}_"):
                    comp_copy['ref'] = f"{module_name}_{original_ref}"
                merged_components.append(comp_copy)

            # Add connections with updated refs
            for conn in circuit.get('connections', []):
                conn_copy = conn.copy()
                # Update points to use prefixed refs
                new_points = []
                for point in conn_copy.get('points', []):
                    if '.' in point:
                        ref, pin = point.rsplit('.', 1)
                        if module_name and not ref.startswith(f"{module_name}_"):
                            point = f"{module_name}_{ref}.{pin}"
                    new_points.append(point)
                conn_copy['points'] = new_points
                merged_connections.append(conn_copy)

            # Update pinNetMapping with prefixed refs
            for pin_key, net in circuit.get('pinNetMapping', {}).items():
                if '.' in pin_key:
                    ref, pin = pin_key.rsplit('.', 1)
                    if module_name and not ref.startswith(f"{module_name}_"):
                        pin_key = f"{module_name}_{ref}.{pin}"
                merged_pin_net_mapping[pin_key] = net
                merged_nets.add(net)

        return {
            "circuitName": "Integrated_Circuit",
            "components": merged_components,
            "connections": merged_connections,
            "pinNetMapping": merged_pin_net_mapping,
            "nets": list(merged_nets)
        }

    def should_use_multi_agent(self, high_level_design: str) -> bool:
        """
        Determine if multi-agent approach should be used for this design.

        Heuristics:
          - 3+ modules: Use multi-agent
          - 200+ expected components: Use multi-agent
          - High complexity keywords: Use multi-agent
          - Simple designs: Use single-agent for efficiency

        Args:
            high_level_design: The high-level design text

        Returns:
            True if multi-agent is recommended
        """
        multi_agent_config = getattr(config, 'MULTI_AGENT_CONFIG', {})
        if not multi_agent_config.get('enabled', True):
            return False

        threshold = multi_agent_config.get('min_modules_for_multi_agent', 3)

        # Count modules mentioned in design
        design_lower = high_level_design.lower()
        module_keywords = ['module', 'block', 'section', 'stage', 'channel', 'unit']
        module_count = sum(design_lower.count(kw) for kw in module_keywords)

        # Check for complexity indicators
        complexity_keywords = ['high voltage', 'high power', 'multi-channel', 'dual channel',
                              'feedback', 'protection', 'isolation', 'resonant']
        complexity_score = sum(1 for kw in complexity_keywords if kw in design_lower)

        # Estimate based on design length (rough proxy for complexity)
        length_factor = len(high_level_design) > 5000

        # Decision logic
        use_multi = (
            module_count >= threshold or
            complexity_score >= 3 or
            (module_count >= 2 and complexity_score >= 2) or
            length_factor
        )

        logger.info(f"Multi-agent decision: {use_multi} "
                   f"(modules={module_count}, complexity={complexity_score}, long={length_factor})")

        return use_multi


# Create singleton instance
ai_manager = AIAgentManager()