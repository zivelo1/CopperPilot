# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 1.1: Requirements Archiver
Converts and saves user requirements in multiple formats for future LLM training

This module runs after Step 1 to archive user requirements in formats suitable
for training future LLM models. It creates comprehensive documentation that includes:
- Original user input
- AI-extracted specifications
- Conversation context
- System metadata

The archived data can be used to:
1. Train or fine-tune LLM models
2. Build a dataset of circuit design patterns
3. Improve AI prompt engineering
4. Create test cases for validation

Author: Circuit Design Automation System
Version: 1.0
Date: 2025-10-20
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from io import BytesIO
import hashlib

# Optional imports for different output formats
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# Use relative imports
import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils.logger import setup_logger

logger = setup_logger(__name__)


class Step11RequirementsArchiver:
    """
    Step 1.1: Requirements Archiver

    Converts user requirements from Step 1 into multiple formats suitable for:
    - LLM training data
    - Circuit design pattern analysis
    - System validation and testing
    - Documentation and audit trails

    Output Formats:
    - JSON: Machine-readable structured data
    - Markdown: Human-readable documentation
    - PDF: Professional formatted document (if reportlab available)
    - TXT: Simple plaintext for basic parsing
    """

    def __init__(self, project_id: str, run_id: str):
        """
        Initialize the Requirements Archiver

        Args:
            project_id (str): Unique project identifier
            run_id (str): Unique run identifier (timestamp-hash format)
        """
        self.project_id = project_id
        self.run_id = run_id
        self.logger = logger

        # Define output paths
        self.base_output_dir = Path("output") / run_id
        self.training_data_dir = self.base_output_dir / "training_data"
        self.logs_training_dir = Path("logs") / "runs" / run_id / "ai_training"

        # Create directories if they don't exist
        self.training_data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_training_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Requirements Archiver initialized for run: {run_id}")
        self.logger.info(f"Training data directory: {self.training_data_dir}")

    async def process(self, step1_output: Dict[str, Any],
                     original_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main processing function - Archives requirements in multiple formats

        Args:
            step1_output (dict): Output from Step 1 (AI-extracted specs)
            original_input (dict): Original user input (raw requirements)

        Returns:
            dict: Status and paths to generated files
        """
        try:
            self.logger.info("=" * 70)
            self.logger.info("STEP 1.1: REQUIREMENTS ARCHIVER")
            self.logger.info(f"Run ID: {self.run_id}")
            self.logger.info("=" * 70)

            # Prepare comprehensive data package
            archive_data = self._prepare_archive_data(step1_output, original_input)

            # Generate timestamp for file naming
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Generate files in multiple formats
            generated_files = {}

            # 1. JSON Format (structured data for LLM training)
            json_path = await self._generate_json(archive_data, timestamp)
            generated_files['json'] = str(json_path)

            # 2. Markdown Format (human-readable documentation)
            markdown_path = await self._generate_markdown(archive_data, timestamp)
            generated_files['markdown'] = str(markdown_path)

            # 3. Plaintext Format (simple text for basic parsing)
            txt_path = await self._generate_txt(archive_data, timestamp)
            generated_files['txt'] = str(txt_path)

            # 4. PDF Format (professional documentation) - optional
            if HAS_REPORTLAB:
                pdf_path = await self._generate_pdf(archive_data, timestamp)
                generated_files['pdf'] = str(pdf_path)
            else:
                self.logger.warning("reportlab not installed - skipping PDF generation")
                self.logger.info("To enable PDF generation: pip install reportlab")

            # 5. Create index file for easy discovery
            await self._generate_index(generated_files, timestamp)

            # Log completion
            self.logger.info("=" * 70)
            self.logger.info("STEP 1.1 COMPLETED SUCCESSFULLY")
            self.logger.info(f"Files generated: {len(generated_files)}")
            for format_type, file_path in generated_files.items():
                self.logger.info(f"  - {format_type.upper()}: {file_path}")
            self.logger.info("=" * 70)

            return {
                "success": True,
                "files_generated": generated_files,
                "training_data_dir": str(self.training_data_dir),
                "timestamp": timestamp
            }

        except Exception as e:
            self.logger.error(f"Error in Step 1.1: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def _prepare_archive_data(self, step1_output: Dict[str, Any],
                             original_input: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare comprehensive data package for archiving

        This creates a complete snapshot of the user requirements and AI processing
        suitable for LLM training and analysis.

        Args:
            step1_output (dict): Processed output from Step 1
            original_input (dict): Raw user input

        Returns:
            dict: Comprehensive data package
        """
        # Extract key information
        facts = step1_output.get('facts', {})
        device_purpose = facts.get('devicePurpose', 'Unknown')
        specifications = facts.get('generalSpecifications', {})

        # Calculate complexity estimate
        complexity = self._estimate_complexity(specifications)

        # Prepare archive data
        archive_data = {
            "metadata": {
                "run_id": self.run_id,
                "project_id": self.project_id,
                "timestamp": datetime.now().isoformat(),
                "version": "1.0",
                "step": "1.1_requirements_archiver",
                "purpose": "LLM training data and circuit design pattern analysis"
            },
            "user_requirements": {
                "original_text": original_input.get('requirements',
                                                    original_input.get('chatInput', '')),
                "pdf_included": bool(original_input.get('pdf_content')),
                "pdf_length": len(original_input.get('pdf_content', '')) if original_input.get('pdf_content') else 0,
                "image_included": bool(original_input.get('image_content')),
                "conversation_history": original_input.get('messages', [])
            },
            "ai_extracted_specs": {
                "device_purpose": device_purpose,
                "specifications": specifications,
                "needs_clarification": step1_output.get('needs_clarification', False),
                "ai_reply": step1_output.get('reply', ''),
                "complete_facts": facts
            },
            "circuit_analysis": {
                "estimated_complexity": complexity,
                "circuit_type": self._classify_circuit_type(device_purpose, specifications),
                "estimated_component_count": self._estimate_component_count(specifications),
                "voltage_levels": self._extract_voltage_levels(specifications),
                "power_requirements": self._extract_power_requirements(specifications)
            },
            "training_metadata": {
                "suitable_for": [
                    "LLM fine-tuning",
                    "Circuit pattern recognition",
                    "Requirements extraction training",
                    "Specification validation"
                ],
                "tags": self._generate_tags(device_purpose, specifications),
                "difficulty_level": complexity
            }
        }

        return archive_data

    def _estimate_complexity(self, specifications: Dict[str, Any]) -> str:
        """
        Estimate circuit complexity based on specifications

        Returns:
            str: 'simple', 'medium', or 'complex'
        """
        # Count specification complexity indicators
        spec_count = len(specifications)

        # Check for multi-channel indicators
        multi_channel = any(
            'channel' in str(v).lower() or 'ch' in str(k).lower()
            for k, v in specifications.items()
        )

        # Check for high power/voltage
        high_power = any(
            ('voltage' in str(k).lower() and any(c.isdigit() and int(c) > 50 for c in str(v)))
            or ('power' in str(k).lower() and any(c.isdigit() and int(c) > 100 for c in str(v)))
            for k, v in specifications.items()
        )

        # Classify complexity
        if spec_count <= 3 and not multi_channel and not high_power:
            return 'simple'
        elif spec_count <= 8 or multi_channel or high_power:
            return 'medium'
        else:
            return 'complex'

    def _classify_circuit_type(self, device_purpose: str,
                               specifications: Dict[str, Any]) -> str:
        """
        Classify circuit type based on purpose and specs

        Returns:
            str: Circuit classification
        """
        purpose_lower = device_purpose.lower()

        # Common circuit type keywords
        if any(word in purpose_lower for word in ['amplifier', 'amp', 'driver']):
            return 'amplifier'
        elif any(word in purpose_lower for word in ['power supply', 'regulator', 'psu']):
            return 'power_supply'
        elif any(word in purpose_lower for word in ['controller', 'microcontroller', 'mcu']):
            return 'controller'
        elif any(word in purpose_lower for word in ['sensor', 'detector', 'measurement']):
            return 'sensor_interface'
        elif any(word in purpose_lower for word in ['led', 'lighting', 'display']):
            return 'led_driver'
        elif any(word in purpose_lower for word in ['motor', 'servo', 'actuator']):
            return 'motor_control'
        elif any(word in purpose_lower for word in ['filter', 'processing', 'signal']):
            return 'signal_processing'
        elif any(word in purpose_lower for word in ['communication', 'rf', 'transceiver']):
            return 'communication'
        else:
            return 'general_purpose'

    def _estimate_component_count(self, specifications: Dict[str, Any]) -> Dict[str, Any]:
        """
        Estimate component count based on specifications

        Returns:
            dict: Component count estimates
        """
        # Count channels/modules
        channel_count = 0
        for k, v in specifications.items():
            if 'channel' in str(k).lower():
                try:
                    # Try to extract number
                    import re
                    numbers = re.findall(r'\d+', str(v))
                    if numbers:
                        channel_count = max(channel_count, int(numbers[0]))
                except:
                    channel_count = max(channel_count, 1)

        # Estimate based on complexity
        base_estimate = {
            'minimum': 5 if channel_count == 0 else 10 * channel_count,
            'maximum': 20 if channel_count == 0 else 50 * channel_count,
            'channels': channel_count if channel_count > 0 else 1
        }

        return base_estimate

    def _extract_voltage_levels(self, specifications: Dict[str, Any]) -> list:
        """Extract voltage levels from specifications"""
        import re
        voltages = []

        for k, v in specifications.items():
            if 'voltage' in str(k).lower() or 'v' in str(k).lower():
                # Extract numbers with V or voltage
                matches = re.findall(r'(\d+(?:\.\d+)?)\s*[Vv]', str(v))
                voltages.extend([float(m) for m in matches])

        return sorted(set(voltages))

    def _extract_power_requirements(self, specifications: Dict[str, Any]) -> Dict[str, Any]:
        """Extract power requirements from specifications"""
        import re
        power_info = {}

        for k, v in specifications.items():
            if 'power' in str(k).lower():
                # Extract watts
                matches = re.findall(r'(\d+(?:\.\d+)?)\s*[Ww]', str(v))
                if matches:
                    power_info['watts'] = [float(m) for m in matches]

                # Extract amps
                matches = re.findall(r'(\d+(?:\.\d+)?)\s*[Aa]', str(v))
                if matches:
                    power_info['amps'] = [float(m) for m in matches]

        return power_info

    def _generate_tags(self, device_purpose: str,
                      specifications: Dict[str, Any]) -> list:
        """Generate searchable tags for training data"""
        tags = []

        # Add purpose-based tags
        tags.append(f"purpose:{device_purpose.lower().replace(' ', '_')}")

        # Add specification-based tags
        for key in specifications.keys():
            tags.append(f"spec:{key.lower().replace(' ', '_')}")

        # Add complexity tag
        tags.append(f"complexity:{self._estimate_complexity(specifications)}")

        # Add circuit type tag
        tags.append(f"type:{self._classify_circuit_type(device_purpose, specifications)}")

        return tags

    async def _generate_json(self, archive_data: Dict[str, Any],
                            timestamp: str) -> Path:
        """
        Generate JSON format file

        JSON format is ideal for:
        - Machine learning training pipelines
        - Automated testing and validation
        - Database storage
        - API integrations
        """
        filename = f"requirements_{timestamp}.json"
        json_path = self.training_data_dir / filename

        # Write formatted JSON
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, indent=2, ensure_ascii=False)

        # Also save to logs/ai_training for consistency
        logs_json_path = self.logs_training_dir / filename
        with open(logs_json_path, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Generated JSON: {json_path}")
        return json_path

    async def _generate_markdown(self, archive_data: Dict[str, Any],
                                timestamp: str) -> Path:
        """
        Generate Markdown format file

        Markdown format is ideal for:
        - Human readability
        - Documentation systems
        - Version control systems
        - Web rendering
        """
        filename = f"requirements_{timestamp}.md"
        markdown_path = self.training_data_dir / filename

        # Build markdown content
        md_content = self._build_markdown_content(archive_data)

        # Write markdown file
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        # Also save to logs/ai_training
        logs_md_path = self.logs_training_dir / filename
        with open(logs_md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        self.logger.info(f"Generated Markdown: {markdown_path}")
        return markdown_path

    def _build_markdown_content(self, archive_data: Dict[str, Any]) -> str:
        """Build markdown content from archive data"""
        metadata = archive_data['metadata']
        user_req = archive_data['user_requirements']
        ai_specs = archive_data['ai_extracted_specs']
        circuit_analysis = archive_data['circuit_analysis']
        training_meta = archive_data['training_metadata']

        md = f"""# Circuit Design Requirements Archive

## Metadata
- **Run ID**: {metadata['run_id']}
- **Timestamp**: {metadata['timestamp']}
- **Version**: {metadata['version']}
- **Purpose**: {metadata['purpose']}

---

## User Requirements

### Original Text Input
```
{user_req['original_text']}
```

### Additional Context
- **PDF Included**: {user_req['pdf_included']}
- **PDF Length**: {user_req['pdf_length']} bytes
- **Image Included**: {user_req['image_included']}
- **Conversation History**: {len(user_req['conversation_history'])} messages

---

## AI-Extracted Specifications

### Device Purpose
{ai_specs['device_purpose']}

### Specifications
"""

        # Add specifications table
        for key, value in ai_specs['specifications'].items():
            md += f"- **{key}**: {value}\n"

        md += f"""
### AI Processing
- **Needs Clarification**: {ai_specs['needs_clarification']}
- **AI Reply**: {ai_specs['ai_reply']}

---

## Circuit Analysis

### Complexity Assessment
- **Estimated Complexity**: {circuit_analysis['estimated_complexity']}
- **Circuit Type**: {circuit_analysis['circuit_type']}
- **Estimated Components**: {circuit_analysis['estimated_component_count']}
- **Voltage Levels**: {circuit_analysis['voltage_levels']}
- **Power Requirements**: {circuit_analysis['power_requirements']}

---

## Training Metadata

### Suitable For
"""
        for item in training_meta['suitable_for']:
            md += f"- {item}\n"

        md += f"""
### Tags
{', '.join(training_meta['tags'])}

### Difficulty Level
{training_meta['difficulty_level']}

---

*Generated by Circuit Design Automation System - Step 1.1*
*This document is part of LLM training dataset for electronics design automation*
"""

        return md

    async def _generate_txt(self, archive_data: Dict[str, Any],
                           timestamp: str) -> Path:
        """
        Generate plain text format file

        TXT format is ideal for:
        - Basic text processing
        - Legacy system compatibility
        - Simple parsing scripts
        - Quick human review
        """
        filename = f"requirements_{timestamp}.txt"
        txt_path = self.training_data_dir / filename

        # Build plain text content
        txt_content = self._build_txt_content(archive_data)

        # Write text file
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(txt_content)

        # Also save to logs/ai_training
        logs_txt_path = self.logs_training_dir / filename
        with open(logs_txt_path, 'w', encoding='utf-8') as f:
            f.write(txt_content)

        self.logger.info(f"Generated TXT: {txt_path}")
        return txt_path

    def _build_txt_content(self, archive_data: Dict[str, Any]) -> str:
        """Build plain text content from archive data"""
        metadata = archive_data['metadata']
        user_req = archive_data['user_requirements']
        ai_specs = archive_data['ai_extracted_specs']
        circuit_analysis = archive_data['circuit_analysis']

        txt = f"""CIRCUIT DESIGN REQUIREMENTS ARCHIVE
{'=' * 70}

RUN ID: {metadata['run_id']}
TIMESTAMP: {metadata['timestamp']}
VERSION: {metadata['version']}

{'=' * 70}
USER REQUIREMENTS
{'=' * 70}

{user_req['original_text']}

PDF Included: {user_req['pdf_included']}
Image Included: {user_req['image_included']}

{'=' * 70}
AI-EXTRACTED SPECIFICATIONS
{'=' * 70}

Device Purpose: {ai_specs['device_purpose']}

Specifications:
"""

        for key, value in ai_specs['specifications'].items():
            txt += f"  - {key}: {value}\n"

        txt += f"""
AI Processing:
  - Needs Clarification: {ai_specs['needs_clarification']}
  - AI Reply: {ai_specs['ai_reply']}

{'=' * 70}
CIRCUIT ANALYSIS
{'=' * 70}

Complexity: {circuit_analysis['estimated_complexity']}
Circuit Type: {circuit_analysis['circuit_type']}
Estimated Components: {circuit_analysis['estimated_component_count']}
Voltage Levels: {circuit_analysis['voltage_levels']}
Power Requirements: {circuit_analysis['power_requirements']}

{'=' * 70}
Generated by Circuit Design Automation System - Step 1.1
For LLM training and circuit design pattern analysis
{'=' * 70}
"""

        return txt

    async def _generate_pdf(self, archive_data: Dict[str, Any],
                           timestamp: str) -> Path:
        """
        Generate PDF format file

        PDF format is ideal for:
        - Professional documentation
        - Printing and archival
        - Executive presentations
        - Formal reports

        Requires: pip install reportlab
        """
        filename = f"requirements_{timestamp}.pdf"
        pdf_path = self.training_data_dir / filename

        # Create PDF document
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )

        # Build PDF content
        story = []
        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a237e'),
            spaceAfter=30,
            alignment=TA_CENTER
        )

        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#303f9f'),
            spaceAfter=12,
            spaceBefore=12
        )

        # Title
        story.append(Paragraph("Circuit Design Requirements", title_style))
        story.append(Spacer(1, 0.2 * inch))

        # Metadata section
        metadata = archive_data['metadata']
        story.append(Paragraph("Document Information", heading_style))
        metadata_data = [
            ['Run ID:', metadata['run_id']],
            ['Timestamp:', metadata['timestamp']],
            ['Version:', metadata['version']],
            ['Purpose:', metadata['purpose']]
        ]
        metadata_table = Table(metadata_data, colWidths=[2*inch, 4.5*inch])
        metadata_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey)
        ]))
        story.append(metadata_table)
        story.append(Spacer(1, 0.3 * inch))

        # User Requirements section
        user_req = archive_data['user_requirements']
        story.append(Paragraph("User Requirements", heading_style))
        story.append(Paragraph(user_req['original_text'], styles['Normal']))
        story.append(Spacer(1, 0.2 * inch))

        # AI-Extracted Specifications section
        ai_specs = archive_data['ai_extracted_specs']
        story.append(Paragraph("AI-Extracted Specifications", heading_style))
        story.append(Paragraph(f"<b>Device Purpose:</b> {ai_specs['device_purpose']}", styles['Normal']))
        story.append(Spacer(1, 0.1 * inch))

        # Specifications table
        spec_data = [['Specification', 'Value']]
        for key, value in ai_specs['specifications'].items():
            spec_data.append([key, str(value)])

        spec_table = Table(spec_data, colWidths=[2.5*inch, 4*inch])
        spec_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))
        story.append(spec_table)
        story.append(Spacer(1, 0.3 * inch))

        # Circuit Analysis section
        circuit_analysis = archive_data['circuit_analysis']
        story.append(Paragraph("Circuit Analysis", heading_style))
        analysis_data = [
            ['Complexity:', circuit_analysis['estimated_complexity']],
            ['Circuit Type:', circuit_analysis['circuit_type']],
            ['Est. Components:', str(circuit_analysis['estimated_component_count'])],
            ['Voltage Levels:', str(circuit_analysis['voltage_levels'])],
            ['Power Requirements:', str(circuit_analysis['power_requirements'])]
        ]
        analysis_table = Table(analysis_data, colWidths=[2*inch, 4.5*inch])
        analysis_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey)
        ]))
        story.append(analysis_table)

        # Build PDF
        doc.build(story)

        self.logger.info(f"Generated PDF: {pdf_path}")
        return pdf_path

    async def _generate_index(self, generated_files: Dict[str, str],
                             timestamp: str) -> None:
        """
        Generate an index file for easy discovery of training data

        This index helps automated systems find and process training data
        """
        index_path = self.training_data_dir / "index.json"

        # Load existing index or create new one
        if index_path.exists():
            with open(index_path, 'r') as f:
                index_data = json.load(f)
        else:
            index_data = {
                "version": "1.0",
                "description": "Index of archived requirements for LLM training",
                "entries": []
            }

        # Add new entry
        new_entry = {
            "timestamp": timestamp,
            "run_id": self.run_id,
            "files": generated_files,
            "created_at": datetime.now().isoformat()
        }

        index_data['entries'].append(new_entry)
        index_data['last_updated'] = datetime.now().isoformat()
        index_data['total_entries'] = len(index_data['entries'])

        # Write updated index
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Updated index: {index_path}")


# Standalone function for easy integration
async def archive_requirements(project_id: str, run_id: str,
                               step1_output: Dict[str, Any],
                               original_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to archive requirements

    Args:
        project_id (str): Project identifier
        run_id (str): Run identifier
        step1_output (dict): Step 1 processed output
        original_input (dict): Original user input

    Returns:
        dict: Status and generated file paths
    """
    archiver = Step11RequirementsArchiver(project_id, run_id)
    return await archiver.process(step1_output, original_input)
