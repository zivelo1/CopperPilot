# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 1: Information Gathering
Ported from N8N workflow to Python
Collects user requirements and specifications for circuit design
"""

import json
import re
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import hashlib
from io import BytesIO

# PyPDF2 is optional - only import if available
try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

# Use relative imports that will work
import sys
sys.path.append(str(Path(__file__).parent.parent))

from ai_agents.agent_manager import AIAgentManager
from utils.logger import setup_logger, comprehensive_logger
from workflow.state_manager import WorkflowStateManager

logger = setup_logger(__name__)


class Step1InfoGathering:
    """
    Step 1: Information Gathering
    - Processes user requirements
    - Extracts PDF content if provided
    - Identifies missing specifications
    - Manages clarification loop
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.ai_manager = AIAgentManager()
        self.state_manager = WorkflowStateManager()
        self.logger = logger
        self.enhanced_logger = None  # Will be set by workflow

    async def process(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main processing function for Step 1

        Args:
            user_input: Dict containing:
                - chatInput: User's text description
                - files: Optional list of uploaded files (PDFs)
                - messages: Chat history (if continuing conversation)

        Returns:
            Dict containing:
                - reply: Response to user
                - needs_clarification: Boolean if more info needed
                - facts: Extracted specifications
        """

        # Log input
        if self.enhanced_logger:
            self.enhanced_logger.log_step_input('step1_info_gathering', user_input, 'Raw user input')
        try:
            self.logger.info("=" * 60)
            self.logger.info(f"STEP 1: INFORMATION GATHERING")
            self.logger.info(f"Project: {self.project_id}")
            self.logger.info("=" * 60)

            # Log to comprehensive logger for Step 1 tab
            comprehensive_logger.log_step("step1_info", "=" * 60)
            comprehensive_logger.log_step("step1_info", f"STEP 1: INFORMATION GATHERING")
            comprehensive_logger.log_step("step1_info", f"Project: {self.project_id}")
            comprehensive_logger.log_step("step1_info", f"Requirements: {user_input.get('requirements', '')[:500]}..." if len(user_input.get('requirements', '')) > 500 else f"Requirements: {user_input.get('requirements', '')}")
            if user_input.get('pdf_content'):
                comprehensive_logger.log_step("step1_info", f"PDF Content: {len(user_input.get('pdf_content', ''))} bytes")
            if user_input.get('image_content'):
                comprehensive_logger.log_step("step1_info", f"Image provided: Yes")

            # Handle PDF content if provided (from API)
            files = user_input.get('files', [])
            if not files and user_input.get('pdf_content'):
                files = [{
                    'mimeType': 'application/pdf',
                    'data': user_input['pdf_content']
                }]

            # Extract PDF text if provided
            pdf_text = await self._extract_pdf_text(files)

            # Log PDF extraction status
            if pdf_text:
                self.logger.info(f"Successfully extracted PDF text: {len(pdf_text)} characters")
                comprehensive_logger.log_step("step1_info", f"PDF text extracted: {pdf_text[:500]}...")
            else:
                self.logger.info("No PDF text extracted")
                comprehensive_logger.log_step("step1_info", "No PDF text extracted")

            # Combine user input with PDF text
            # Handle 'requirements' field from API or 'chatInput' from web
            chat_input = user_input.get('requirements', user_input.get('chatInput', ''))
            combined_input = self._combine_inputs(
                chat_input,
                pdf_text,
                user_input.get('messages', [])
            )

            # Log combined input
            self.logger.info(f"Combined input prepared: chatInput={len(combined_input.get('chatInput', ''))} chars, text={len(combined_input.get('text', ''))} chars")

            # Process with AI agent
            ai_response = await self._process_with_ai(combined_input)

            # Normalize the output
            normalized_output = self._normalize_output(ai_response)

            # Check for duplicate questions (prevent loops)
            normalized_output = self._check_duplicate_questions(normalized_output)

            # Save to state
            self.state_manager.update_state('step_1_output', normalized_output)

            # Log completion
            self.logger.info("=" * 60)
            self.logger.info(f"STEP 1 COMPLETED")
            self.logger.info(f"  Needs clarification: {normalized_output['needs_clarification']}")
            self.logger.info(f"  Device purpose: {normalized_output['facts']['devicePurpose']}")
            self.logger.info(f"  Specifications extracted: {len(normalized_output['facts']['generalSpecifications'])} items")
            for key, value in normalized_output['facts']['generalSpecifications'].items():
                self.logger.info(f"    - {key}: {value}")
            self.logger.info(f"  AI Reply: {normalized_output['reply'][:300]}..." if len(normalized_output['reply']) > 300 else f"  AI Reply: {normalized_output['reply']}")

            # Log to comprehensive logger for Step 1 tab
            comprehensive_logger.log_step("step1_info", "=" * 60)
            comprehensive_logger.log_step("step1_info", f"STEP 1 COMPLETED")
            comprehensive_logger.log_step("step1_info", f"  Device Purpose: {normalized_output['facts']['devicePurpose']}")
            comprehensive_logger.log_step("step1_info", f"  Specifications: {json.dumps(normalized_output['facts']['generalSpecifications'], indent=2)}")
            comprehensive_logger.log_step("step1_info", f"  Full Facts: {json.dumps(normalized_output['facts'], indent=2)}")
            comprehensive_logger.log_step("step1_info", f"  AI Reply: {normalized_output['reply']}")
            comprehensive_logger.log_step("step1_info", f"  Needs clarification: {normalized_output['needs_clarification']}")
            comprehensive_logger.log_step("step1_info", "=" * 60)
            self.logger.info("=" * 60)

            if self.enhanced_logger:
                self.enhanced_logger.log_step_output('step1_info_gathering', normalized_output, 'Step 1 results')
            return normalized_output

        except Exception as e:
            self.logger.error(f"Error in Step 1: {str(e)}")
            raise

    async def _extract_pdf_text(self, files: list) -> str:
        """Extract text from PDF files if provided"""
        if not files:
            return ""

        pdf_text = ""
        for file in files:
            if file.get('mimeType') == 'application/pdf':
                try:
                    # Extract PDF content
                    pdf_content = file.get('data', b'')
                    if isinstance(pdf_content, str):
                        # Base64 encoded
                        import base64
                        pdf_content = base64.b64decode(pdf_content)

                    if not HAS_PYPDF2:
                        self.logger.warning("PyPDF2 not installed - cannot extract PDF text")
                        return ""
                    pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_content))
                    for page in pdf_reader.pages:
                        pdf_text += page.extract_text() + "\n"

                    self.logger.info(f"Extracted {len(pdf_text)} characters from PDF")
                except Exception as e:
                    self.logger.error(f"Error extracting PDF: {str(e)}")

        return pdf_text

    def _combine_inputs(self, chat_input: str, pdf_text: str, messages: list) -> Dict[str, Any]:
        """Combine all inputs for AI processing"""
        # Build conversation history
        conversation = ""
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            conversation += f"{role}: {content}\n"

        # Add current input
        conversation += f"user: {chat_input}\n"

        return {
            'chatInput': chat_input,
            'text': pdf_text or "none",
            'conversation': conversation
        }

    async def _process_with_ai(self, combined_input: Dict[str, Any]) -> Dict[str, Any]:
        """Process the input with AI agent"""

        # Load the Step 1 prompt from correct location
        prompt_path = Path(__file__).parent.parent / "ai_agents" / "prompts" / "AI Agent - Step 1 - Prompt.txt"

        if prompt_path.exists():
            with open(prompt_path, 'r') as f:
                prompt_template = f.read()
        else:
            # Fallback prompt if file not found
            self.logger.warning(f"Prompt file not found at {prompt_path}, using fallback")
            prompt_template = self._get_fallback_prompt()

        # Replace variables in prompt - IMPORTANT: Must replace PDF text AFTER chatInput
        prompt = prompt_template.replace('{{ $json.chatInput }}', combined_input['chatInput'])
        prompt = prompt.replace('{{ $json.text || "none" }}', combined_input['text'])

        # Log prompt details
        self.logger.info(f"Prompt prepared - PDF text included: {len(combined_input.get('text', '')) > 10}")
        comprehensive_logger.log_step("step1_info", f"PDF text in prompt: {'Yes' if len(combined_input.get('text', '')) > 10 else 'No'} ({len(combined_input.get('text', ''))} chars)")

        # Additional logging to verify PDF is being sent
        if len(combined_input.get('text', '')) > 10:
            comprehensive_logger.log_step("step1_info", f"PDF text preview (first 500 chars): {combined_input['text'][:500]}...")
            self.logger.info(f"PDF content is being sent to AI - first 200 chars: {combined_input['text'][:200]}...")

        # Call AI with Claude 4 Sonnet
        result = await self.ai_manager.call_ai(
            step_name="step_1",
            prompt=prompt,
            context={"user_input": combined_input}
        )

        response = result.get('parsed_response', result.get('raw_response', {}))

        return response

    def _normalize_output(self, ai_response: Any) -> Dict[str, Any]:
        """
        Normalize AI output to expected format
        Handles various response formats from AI
        """

        def robust_parse(jsonish):
            """Robust JSON parsing"""
            if isinstance(jsonish, dict):
                return jsonish
            if isinstance(jsonish, list) and len(jsonish) > 0:
                return jsonish[0]

            if not isinstance(jsonish, str):
                raise ValueError("No JSON string to parse")

            s = jsonish.strip()

            # Remove code fences if present
            s = re.sub(r'^```json\s*', '', s, flags=re.IGNORECASE)
            s = re.sub(r'```$', '', s)
            s = s.strip()

            # Extract JSON object
            if not (s.startswith('{') or s.startswith('[')):
                start = max(s.find('{'), s.find('['))
                if s.find('{') >= 0 and s.find('[') >= 0:
                    start = min(s.find('{'), s.find('['))

                if start != -1:
                    # Find matching close
                    if s[start] == '{':
                        end = s.rfind('}')
                    else:
                        end = s.rfind(']')

                    if end > start:
                        s = s[start:end + 1]

            return json.loads(s)

        def clean_reply(reply_raw: str) -> str:
            """Clean and format the reply text"""
            if not reply_raw:
                return ""

            # Strip HTML tags
            text = re.sub(r'<br\s*/?>', '\n', reply_raw, flags=re.IGNORECASE)
            text = re.sub(r'</p>\s*<p>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'</?[^>]+>', '', text)
            text = text.replace('&nbsp;', ' ')

            # Clean whitespace
            text = re.sub(r'\t', ' ', text)
            text = re.sub(r'\n{2,}', '\n', text)
            text = text.strip()

            if not text:
                return ""

            lines = [line.strip() for line in text.split('\n') if line.strip()]

            # Check for success message
            success = "All specs received. Proceeding to high-level design."
            if ' '.join(lines) == success:
                return success

            # Process clarification questions
            header = "I still need these details:"
            start_idx = 0

            if lines and lines[0].lower().startswith('i still need'):
                start_idx = 1

            # Extract questions and renumber
            # CRITICAL FIX: Only treat lines starting with a number as questions
            # Lines starting with (e.g., or indented are examples, not questions
            questions = []
            for line in lines[start_idx:]:
                stripped = line.strip()
                # Skip example lines - they start with (e.g., or are indented examples
                if stripped.startswith('(e.g.,') or stripped.startswith('(eg,') or stripped.startswith('(example'):
                    # Append to previous question if exists
                    if questions:
                        questions[-1] += ' ' + stripped
                    continue
                # Only process lines that look like questions (start with number or are actual questions)
                # Remove existing numbering
                q = re.sub(r'^\d+\.\s*', '', stripped).strip()
                if q and not q.startswith('('):  # Skip any line starting with parenthesis
                    questions.append(q)

            # Deduplicate questions
            seen = set()
            unique_questions = []
            for q in questions:
                # Normalize for dedup but keep original
                key = re.sub(r'\s+', '', q.lower())
                # Remove example portion for dedup comparison
                key = re.sub(r'\(e\.g\..*?\)', '', key)
                if key not in seen:
                    seen.add(key)
                    unique_questions.append(q)

            # Limit to 7 questions and renumber
            final_questions = [f"{i+1}. {q}" for i, q in enumerate(unique_questions[:7])]

            if final_questions:
                return header + '\n' + '\n'.join(final_questions)
            elif lines:
                return lines[0]
            else:
                return ""

        try:
            # Parse AI response
            obj = robust_parse(ai_response)

            # Handle array wrapper
            if isinstance(obj, list) and len(obj) > 0:
                obj = obj[0]

            # Build normalized output
            normalized = {
                'reply': '',
                'needs_clarification': bool(obj.get('needs_clarification', False)),
                'facts': {
                    'devicePurpose': obj.get('facts', {}).get('devicePurpose', ''),
                    'generalSpecifications': obj.get('facts', {}).get('generalSpecifications', {})
                }
            }

            # Clean the reply
            reply_raw = (obj.get('reply') or
                        obj.get('chat_response') or
                        obj.get('message') or
                        '')

            normalized['reply'] = clean_reply(reply_raw)

            return normalized

        except Exception as e:
            self.logger.error(f"Error normalizing output: {str(e)}")
            # Return safe default
            return {
                'reply': 'I need more information about your circuit requirements. Please describe what you want to build.',
                'needs_clarification': True,
                'facts': {
                    'devicePurpose': '',
                    'generalSpecifications': {}
                }
            }

    def _check_duplicate_questions(self, output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if we're asking the same questions repeatedly
        Prevents infinite clarification loops
        """
        if not output['needs_clarification']:
            return output

        # Generate hash of current questions
        def generate_hash(text: str) -> str:
            return hashlib.md5(text.encode()).hexdigest()

        current_hash = generate_hash(output['reply'])

        # Check against previous hash
        state = self.state_manager.get_state()
        last_hash = state.get('step_1_questions_hash') if state else None

        if last_hash == current_hash:
            # Same questions - modify reply
            output['reply'] = ('I still need these details:\n'
                              '1. (No changes) Please answer the previously listed questions so I can proceed.')
        else:
            # Save new hash
            self.state_manager.update_state('step_1_questions_hash', current_hash)

        return output

    def _get_fallback_prompt(self) -> str:
        """Fallback prompt if prompt file not found"""
        return """You are an expert electronic engineer. Your primary goal is to understand the user's high-level need for an electronic device or circuit, gather all necessary specifications, and identify any missing information.

CRITICAL: Respond with ONLY a valid JSON array containing a single object.

INPUTS:
* user_description: {{ $json.chatInput }}
* pdf_text: {{ $json.text || "none" }}

TASK:
1. Parse all inputs
2. Understand the core need
3. Extract specifications
4. Identify missing critical information
5. Decide action:
   - If missing critical info: needs_clarification = true
   - If ready: needs_clarification = false

OUTPUT FORMAT:
[{
  "reply": "string",
  "needs_clarification": true or false,
  "facts": {
    "devicePurpose": "string",
    "generalSpecifications": {}
  }
}]"""