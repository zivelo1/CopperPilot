# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 2.5: Project Summary Report (Human-Friendly)
Generates a concise PDF under project_info/ summarizing:
 - What the user requested (original text)
 - What the system will build (high-level modules)
 - High-level diagram (PNG) embedded if available
 - Key information (power demand, voltages, channels, notable specs)

This step is GENERIC and format-agnostic. It does not assume a specific circuit
type. It extracts information from Step 1 (facts/specs) and Step 2 (modules and
diagram) and produces a human-readable summary suitable for handoffs.

If reportlab isn't available, a plaintext/Markdown fallback is produced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Optional PDF generator (reportlab)
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image as RLImage,
        PageBreak,
    )
    HAS_REPORTLAB = True
except Exception:
    HAS_REPORTLAB = False


@dataclass
class Step25ProjectSummary:
    project_id: str
    project_folder: str
    output_root: Path
    project_info_dir: Path
    highlevel_dir: Path

    async def generate(
        self,
        user_requirements_text: str,
        step1_output: Dict[str, Any],
        step2_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate the project summary PDF under project_info/.

        Returns a dict with success flag and paths to generated artifacts.
        """
        self.project_info_dir.mkdir(parents=True, exist_ok=True)

        # Locate the best high-level PNG (system_overview.png preferred)
        diagram_path = self._find_highlevel_png()

        # Extract key info generically from Step 1 facts/specs
        facts = step1_output.get('facts', {}) if isinstance(step1_output, dict) else {}
        device_purpose = facts.get('devicePurpose', '')
        general_specs = facts.get('generalSpecifications', {}) if isinstance(facts, dict) else {}

        key_info = self._extract_key_info(general_specs, user_requirements_text)

        # What the system will build: collect modules from Step 2
        modules = step2_output.get('modules', []) if isinstance(step2_output, dict) else []

        # Build and save the PDF (or fallback)
        pdf_path = self.project_info_dir / 'project_summary.pdf'
        if HAS_REPORTLAB:
            self._build_pdf(
                pdf_path=pdf_path,
                user_text=user_requirements_text,
                device_purpose=device_purpose,
                key_info=key_info,
                modules=modules,
                diagram_path=diagram_path,
            )
        else:
            # Fallback: Write a simple Markdown file
            md_path = self.project_info_dir / 'project_summary.md'
            self._build_markdown(
                md_path=md_path,
                user_text=user_requirements_text,
                device_purpose=device_purpose,
                key_info=key_info,
                modules=modules,
                diagram_path=diagram_path,
            )

        return {
            'success': True,
            'pdf_path': str(pdf_path) if HAS_REPORTLAB else None,
            'fallback_md': None if HAS_REPORTLAB else str(md_path),
            'diagram_used': str(diagram_path) if diagram_path else None,
        }

    def _find_highlevel_png(self) -> Optional[Path]:
        """Pick a high-level PNG to embed; prefer system_overview.png."""
        try:
            candidates = list(self.highlevel_dir.glob('*.png'))
            if not candidates:
                return None
            preferred = self.highlevel_dir / 'system_overview.png'
            if preferred.exists():
                return preferred
            # Otherwise return the first PNG
            return sorted(candidates)[0]
        except Exception:
            return None

    def _extract_key_info(self, specs: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        """Derive voltages, power, channels, and special notes generically."""
        key = {
            'voltage_levels': self._extract_voltages(specs, user_text),
            'power_requirements': self._extract_power(specs, user_text),
            'channel_count': self._extract_channels(specs, user_text),
            'special_notes': self._extract_special(specs, user_text),
        }
        return key

    def _extract_voltages(self, specs: Dict[str, Any], text: str) -> List[str]:
        values = []
        blob = f"{specs} {text}"
        for m in re.findall(r"(\d+(?:\.\d+)?)\s*V(?![a-zA-Z])", blob, flags=re.IGNORECASE):
            try:
                values.append(f"{float(m)} V")
            except Exception:
                pass
        return sorted(set(values))

    def _extract_power(self, specs: Dict[str, Any], text: str) -> List[str]:
        values = []
        blob = f"{specs} {text}"
        for m in re.findall(r"(\d+(?:\.\d+)?)\s*W", blob, flags=re.IGNORECASE):
            try:
                values.append(f"{float(m)} W")
            except Exception:
                pass
        for m in re.findall(r"(\d+(?:\.\d+)?)\s*A", blob, flags=re.IGNORECASE):
            try:
                values.append(f"{float(m)} A")
            except Exception:
                pass
        return sorted(set(values))

    def _extract_channels(self, specs: Dict[str, Any], text: str) -> Optional[int]:
        blob = f"{specs} {text}"
        try:
            m = re.search(r"(\d+)\s*channel", blob, flags=re.IGNORECASE)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return None

    def _extract_special(self, specs: Dict[str, Any], text: str) -> List[str]:
        items: List[str] = []
        # Look for keys commonly used for unique notes
        for k, v in (specs or {}).items():
            if any(tag in str(k).lower() for tag in ['special', 'note', 'constraint', 'requirement']):
                items.append(f"{k}: {v}")
        # Fallback: look for keywords in free text
        for kw in ['isolation', 'high voltage', 'temperature', 'environment', 'safety', 'medical', 'rf', 'hv']:
            if re.search(kw, text, flags=re.IGNORECASE):
                items.append(f"Mentioned: {kw}")
        # Deduplicate
        seen = set()
        deduped = []
        for it in items:
            if it not in seen:
                deduped.append(it)
                seen.add(it)
        return deduped[:8]

    def _build_pdf(
        self,
        pdf_path: Path,
        user_text: str,
        device_purpose: str,
        key_info: Dict[str, Any],
        modules: List[Dict[str, Any]],
        diagram_path: Optional[Path],
    ) -> None:
        """Compose a friendly PDF using reportlab."""
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=48,
            leftMargin=48,
            topMargin=48,
            bottomMargin=36,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'Title', parent=styles['Title'], alignment=TA_CENTER, fontSize=20
        )
        heading = ParagraphStyle('Heading', parent=styles['Heading2'], textColor=colors.HexColor('#1a237e'))
        body = styles['BodyText']

        story: List[Any] = []

        # Title
        story.append(Paragraph("Project Summary", title_style))
        story.append(Spacer(1, 0.2 * inch))

        # What the user requested
        story.append(Paragraph("What You Asked For", heading))
        story.append(Paragraph(device_purpose or "", body))
        if user_text:
            story.append(Spacer(1, 0.1 * inch))
            story.append(Paragraph(user_text.replace('\n', '<br/>'), body))
        story.append(Spacer(1, 0.25 * inch))

        # What the system will build
        story.append(Paragraph("What We Built", heading))
        if modules:
            for m in modules[:12]:
                name = m.get('name', 'Module') if isinstance(m, dict) else str(m)
                desc = ''
                if isinstance(m, dict):
                    desc = m.get('description', '') or ''
                story.append(Paragraph(f"• <b>{name}</b> — {desc}", body))
        else:
            story.append(Paragraph("The system has prepared a modular high-level design.", body))
        story.append(Spacer(1, 0.25 * inch))

        # Key information (power, voltages, channels, specials)
        info_rows = []
        if key_info.get('voltage_levels'):
            info_rows.append(['Voltage levels', ', '.join(key_info['voltage_levels'])])
        if key_info.get('power_requirements'):
            info_rows.append(['Power/Current', ', '.join(key_info['power_requirements'])])
        if key_info.get('channel_count'):
            info_rows.append(['Channels', str(key_info['channel_count'])])
        if key_info.get('special_notes'):
            info_rows.append(['Notes', '; '.join(key_info['special_notes'])])

        if info_rows:
            story.append(Paragraph("Key Information", heading))
            t = Table(info_rows, colWidths=[1.8*inch, 4.7*inch])
            t.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.25 * inch))

        # High-level diagram
        story.append(Paragraph("High-Level Diagram", heading))
        if diagram_path and diagram_path.exists():
            try:
                img = RLImage(str(diagram_path))
                # Scale to fit width while keeping aspect
                max_w = 6.2 * inch
                if img.drawWidth > max_w:
                    ratio = max_w / float(img.drawWidth)
                    img.drawWidth = max_w
                    img.drawHeight = float(img.drawHeight) * ratio
                story.append(img)
            except Exception:
                story.append(Paragraph("Diagram image is available but could not be embedded.", body))
        else:
            story.append(Paragraph("Diagram not available yet.", body))

        doc.build(story)

    def _build_markdown(
        self,
        md_path: Path,
        user_text: str,
        device_purpose: str,
        key_info: Dict[str, Any],
        modules: List[Dict[str, Any]],
        diagram_path: Optional[Path],
    ) -> None:
        """Lightweight fallback when reportlab is not present."""
        lines: List[str] = []
        lines.append("# Project Summary")
        lines.append("")
        lines.append("## What You Asked For")
        if device_purpose:
            lines.append(device_purpose)
        if user_text:
            lines.append("")
            lines.append(user_text)
        lines.append("")
        lines.append("## What We Built")
        for m in modules[:12]:
            name = m.get('name', 'Module') if isinstance(m, dict) else str(m)
            desc = m.get('description', '') if isinstance(m, dict) else ''
            lines.append(f"- {name}: {desc}")
        lines.append("")
        lines.append("## Key Information")
        if key_info.get('voltage_levels'):
            lines.append(f"- Voltage levels: {', '.join(key_info['voltage_levels'])}")
        if key_info.get('power_requirements'):
            lines.append(f"- Power/Current: {', '.join(key_info['power_requirements'])}")
        if key_info.get('channel_count'):
            lines.append(f"- Channels: {key_info['channel_count']}")
        if key_info.get('special_notes'):
            lines.append(f"- Notes: {'; '.join(key_info['special_notes'])}")
        lines.append("")
        lines.append("## High-Level Diagram")
        if diagram_path:
            lines.append(f"(See image file: {diagram_path.name})")
        else:
            lines.append("Not available")
        md_path.write_text("\n".join(lines), encoding='utf-8')

