# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Conversation Logger for Chat Tab
Logs all user inputs and workflow responses
"""
import json
from datetime import datetime
from pathlib import Path
from utils.logger import setup_logger

# Create logger specifically for conversations
conversation_logger = setup_logger("chat.conversations")

class ConversationLogger:
    """Logs conversations for the chat tab"""

    def __init__(self, project_id: str):
        self.project_id = project_id

    def log_user_input(self, requirements: str, pdf_content: str = None, image_content: bool = False):
        """Log what the user sent"""
        conversation_logger.info("="*60)
        conversation_logger.info(f"USER INPUT - Project: {self.project_id}")
        conversation_logger.info(f"Timestamp: {datetime.now().isoformat()}")
        conversation_logger.info(f"Requirements (FULL TEXT):")
        conversation_logger.info(requirements)
        conversation_logger.info("-"*40)

        if pdf_content:
            conversation_logger.info(f"PDF PROVIDED: {len(pdf_content)} bytes")
            # Log full PDF content if it's text
            if isinstance(pdf_content, str):
                conversation_logger.info("PDF Content (FULL TEXT):")
                conversation_logger.info(pdf_content)
            else:
                conversation_logger.info(f"PDF Content: [Binary data - {len(pdf_content)} bytes]")
            conversation_logger.info("-"*40)

        if image_content:
            conversation_logger.info(f"IMAGE PROVIDED: Yes")
            conversation_logger.info("-"*40)

        conversation_logger.info("="*60)

    def log_workflow_response(self, step: str, response: dict):
        """Log workflow responses"""
        conversation_logger.info(f"WORKFLOW RESPONSE - Step: {step}")
        conversation_logger.info(f"Timestamp: {datetime.now().isoformat()}")

        if 'reply' in response:
            conversation_logger.info(f"AI Reply: {response['reply'][:500]}..." if len(response['reply']) > 500 else f"AI Reply: {response['reply']}")

        if 'needs_clarification' in response:
            conversation_logger.info(f"Needs Clarification: {response['needs_clarification']}")

        if 'facts' in response:
            conversation_logger.info(f"Facts Extracted: {json.dumps(response['facts'], indent=2)[:500]}")

        conversation_logger.info("-"*40)