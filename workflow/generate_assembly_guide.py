# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
System Assembly Guide Generator
===============================
Generates a "How to Assemble" PDF guide for the user.
Explains physical connections between modules and power setup.

Location: workflow/generate_assembly_guide.py
Output: output/[run_id]/project_info/assembly_guide.pdf

Logic:
1. Reads High-Level Design (architecture/connections).
2. Reads Low-Level Design (connector details).
3. Uses AI to generate human-friendly assembly instructions.
4. Renders PDF with ReportLab, embedding system diagrams.
"""

import json
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

# ReportLab for PDF generation
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image as RLImage,
        PageBreak,
        ListFlowable,
        ListItem
    )
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# AI Client
try:
    from anthropic import Anthropic
    HAS_AI = True
except ImportError:
    HAS_AI = False

# Central config — used for model selection
try:
    from server.config import config as _cfg
    _ASSEMBLY_MODEL = _cfg.MODELS.get("step_4_optimize_bom", {}).get(
        "model", "claude-sonnet-4-5-20250929"
    )
except ImportError:
    _ASSEMBLY_MODEL = os.environ.get("MODEL_ASSEMBLY_GUIDE", "claude-sonnet-4-5-20250929")

logger = logging.getLogger(__name__)

class AssemblyGuideGenerator:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.project_info_dir = output_dir / "project_info"
        self.highlevel_dir = output_dir / "highlevel"
        self.lowlevel_dir = output_dir / "lowlevel"
        
        self.project_info_dir.mkdir(parents=True, exist_ok=True)

    def generate(self) -> bool:
        """Main entry point to generate the assembly guide."""
        print(f"📝 Generating System Assembly Guide...")
        
        # 1. Load Data
        high_level_data = self._load_json(self.highlevel_dir / "high_level_design.json")
        if not high_level_data:
            print("⚠️  High-level design not found. Skipping assembly guide.")
            return False

        # Load low-level data to get connector specifics (if available)
        low_level_data = self._load_low_level_summaries()

        # 2. Generate Content via AI
        content = self._generate_content_with_ai(high_level_data, low_level_data)
        
        # 3. Create PDF
        if HAS_REPORTLAB:
            pdf_path = self.project_info_dir / "assembly_guide.pdf"
            self._create_pdf(pdf_path, content)
            print(f"✅ Assembly Guide generated: {pdf_path}")
        else:
            # Fallback to Markdown
            md_path = self.project_info_dir / "assembly_guide.md"
            md_path.write_text(content['raw_text'], encoding='utf-8')
            print(f"✅ Assembly Guide (MD) generated: {md_path} (ReportLab not installed)")

        return True

    def _load_json(self, path: Path) -> Optional[Dict]:
        try:
            if path.exists():
                with open(path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {path}: {e}")
        return None

    def _load_low_level_summaries(self) -> List[Dict]:
        """Load brief summaries of low-level circuits to identify connectors."""
        summaries = []
        if not self.lowlevel_dir.exists():
            return summaries
            
        for f in self.lowlevel_dir.glob("circuit_*.json"):
            data = self._load_json(f)
            if data:
                circuit = data.get('circuit', {})
                name = circuit.get('moduleName', f.stem)
                # Extract connectors
                connectors = [
                    c for c in circuit.get('components', []) 
                    if 'connector' in c.get('type', '').lower() or 'header' in c.get('description', '').lower()
                ]
                summaries.append({
                    'name': name,
                    'connectors': connectors
                })
        return summaries

    def _generate_content_with_ai(self, hl_data: Dict, ll_data: List[Dict]) -> Dict[str, Any]:
        """Use AI to write the assembly instructions."""
        
        if not HAS_AI or not os.getenv("ANTHROPIC_API_KEY"):
            return {
                "title": "System Assembly Guide",
                "intro": "This guide explains how to connect the system modules.",
                "steps": ["Manual assembly required based on schematics."],
                "raw_text": "AI generation unavailable. Please refer to schematics."
            }

        prompt = f"""
        You are a technical writer creating a "Hardware Assembly Guide" for an electronic system.
        
        SYSTEM ARCHITECTURE (High Level):
        {json.dumps(hl_data.get('modules', []), indent=2)}
        
        CONNECTIONS (High Level):
        {json.dumps(hl_data.get('connections', []), indent=2)}
        
        MODULE DETAILS (Low Level Connectors):
        {json.dumps(ll_data, indent=2)}
        
        TASK:
        Write a clear, user-friendly guide on how to physically assemble this system.
        Focus on:
        1. MODULE IDENTIFICATION: List the modules the user has.
        2. INTERCONNECTIONS: Explain which module connects to which, and ideally which connector to use (if visible in data).
        3. POWER: Explain how to connect power to the system.
        4. WARNINGS: Double-check polarities, voltage levels, etc.
        
        OUTPUT FORMAT (JSON):
        {{
            "title": "System Assembly Guide",
            "introduction": "Brief overview...",
            "modules_section": ["Bullet point 1", "Bullet point 2"],
            "connections_section": [
                {{"from": "Module A", "to": "Module B", "instruction": "Connect J1 on A to J2 on B..."}}
            ],
            "power_section": "Instructions on connecting power...",
            "safety_notes": ["Warning 1", "Warning 2"]
        }}
        """

        try:
            client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model=_ASSEMBLY_MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text
            # extract json
            import re
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
            else:
                # Fallback
                return {"raw_text": text, "title": "Assembly Guide"}
        except Exception as e:
            logger.error(f"AI generation failed: {e}")
            return {"raw_text": "Could not generate guide.", "title": "Error"}

    def _create_pdf(self, pdf_path: Path, content: Dict):
        """Render the PDF using ReportLab."""
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=50, leftMargin=50,
            topMargin=50, bottomMargin=50
        )
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle('GuideTitle', parent=styles['Title'], fontSize=24, spaceAfter=20, textColor=colors.HexColor('#B87333'))
        h1_style = ParagraphStyle('GuideH1', parent=styles['Heading1'], fontSize=16, spaceBefore=15, spaceAfter=10, textColor=colors.HexColor('#2A2D33'))
        body_style = styles['BodyText']
        body_style.fontSize = 11
        body_style.leading = 14

        story = []

        # 1. Title
        story.append(Paragraph(content.get('title', 'Assembly Guide'), title_style))
        story.append(Spacer(1, 0.2 * inch))

        # 2. Diagram (if available)
        diagram_path = self.highlevel_dir / "system_overview.png"
        if diagram_path.exists():
            try:
                img = RLImage(str(diagram_path))
                # Resize to fit page width
                aspect = img.drawHeight / img.drawWidth
                target_width = 6 * inch
                img.drawWidth = target_width
                img.drawHeight = target_width * aspect
                story.append(img)
                story.append(Spacer(1, 0.2 * inch))
                story.append(Paragraph("<i>Figure 1: System Block Diagram</i>", 
                             ParagraphStyle('Caption', parent=body_style, alignment=TA_CENTER)))
                story.append(Spacer(1, 0.3 * inch))
            except Exception:
                pass

        # 3. Introduction
        if 'introduction' in content:
            story.append(Paragraph(content['introduction'], body_style))
            story.append(Spacer(1, 0.2 * inch))

        # 4. Modules
        if 'modules_section' in content:
            story.append(Paragraph("1. System Modules", h1_style))
            items = [ListItem(Paragraph(m, body_style)) for m in content['modules_section']]
            story.append(ListFlowable(items, bulletType='bullet', start='circle'))
            story.append(Spacer(1, 0.2 * inch))

        # 5. Connections
        if 'connections_section' in content:
            story.append(Paragraph("2. Interconnections", h1_style))
            # Create a table for connections
            table_data = [['From Module', 'To Module', 'Instruction']]
            for conn in content['connections_section']:
                if isinstance(conn, dict):
                    table_data.append([
                        Paragraph(conn.get('from', ''), body_style),
                        Paragraph(conn.get('to', ''), body_style),
                        Paragraph(conn.get('instruction', ''), body_style)
                    ])
            
            if len(table_data) > 1:
                t = Table(table_data, colWidths=[1.5*inch, 1.5*inch, 3*inch])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E0E0E0')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ]))
                story.append(t)
            story.append(Spacer(1, 0.2 * inch))

        # 6. Power
        if 'power_section' in content:
            story.append(Paragraph("3. Power Setup", h1_style))
            story.append(Paragraph(content['power_section'], body_style))
            story.append(Spacer(1, 0.2 * inch))

        # 7. Safety
        if 'safety_notes' in content:
            story.append(Paragraph("⚠️ Safety & Assembly Notes", h1_style))
            for note in content['safety_notes']:
                # Red bold text for warnings
                p = Paragraph(f"• {note}", ParagraphStyle('Warning', parent=body_style, textColor=colors.red))
                story.append(p)

        doc.build(story)

if __name__ == "__main__":
    # Simple CLI for testing
    import sys
    if len(sys.argv) > 1:
        output_path = Path(sys.argv[1])
        gen = AssemblyGuideGenerator(output_path)
        gen.generate()
    else:
        print("Usage: python3 generate_assembly_guide.py <output_run_folder>")
