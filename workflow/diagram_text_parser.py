# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Diagram Text Parser - Converts AI text descriptions to DOT diagrams

Parses a simple text format:
  Module: Module_Name (type: category)
  Connect: Module_A -> Module_B [connection_type]

Produces a styled Graphviz DOT graph with:
- Colored nodes by module type
- Colored/labeled edges by connection type
- Clean left-to-right layout
"""

import re
from typing import Dict, List, Tuple, Any

# -------------------------------------------------------------------------
# Configuration — single source of truth for colors and styling
# -------------------------------------------------------------------------

NODE_COLORS: Dict[str, str] = {
    "power": "#A8D5BA",       # soft green
    "control": "#FFF9C4",     # light yellow
    "signal": "#BBDEFB",      # light blue
    "amplifier": "#FFCDD2",   # light coral
    "driver": "#FFCDD2",      # light coral
    "matching": "#FFE0B2",    # light salmon
    "sensing": "#B2EBF2",     # light cyan
    "feedback": "#B2EBF2",    # light cyan
    "protection": "#E1BEE7",  # light purple
    "thermal": "#D7CCC8",     # light brown
    "interface": "#F0F4C3",   # lime
    "communication": "#C5CAE9",  # indigo light
}

EDGE_STYLES: Dict[str, Dict[str, str]] = {
    "power":         {"color": "#C62828", "style": "bold",   "label": "PWR"},
    "signal":        {"color": "#1565C0", "style": "solid",  "label": "SIG"},
    "control":       {"color": "#2E7D32", "style": "solid",  "label": "CTRL"},
    "feedback":      {"color": "#6A1B9A", "style": "dashed", "label": "FB"},
    "sensing":       {"color": "#00838F", "style": "dashed", "label": "SENS"},
    "thermal":       {"color": "#BF360C", "style": "dotted", "label": "THERM"},
    "communication": {"color": "#37474F", "style": "solid",  "label": "COM"},
}

DEFAULT_NODE_COLOR = "#ECEFF1"  # light grey
DEFAULT_EDGE_STYLE = {"color": "#455A64", "style": "solid", "label": ""}


class DiagramTextParser:
    """Parse text-based diagram descriptions into structured data."""

    def __init__(self):
        self.modules: List[Dict[str, str]] = []
        self.connections: List[Dict[str, str]] = []
        self.errors: List[str] = []

    def parse(self, text: str) -> Dict[str, Any]:
        """Parse text diagram description."""
        self.modules = []
        self.connections = []
        self.errors = []

        lines = text.strip().split('\n')

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line.lower().startswith('module:'):
                self._parse_module(line, line_num)
            elif 'connect:' in line.lower() or '->' in line:
                self._parse_connection(line, line_num)

        if not self.modules:
            self.errors.append("No modules defined")
        if not self.connections:
            self.errors.append("No connections defined")

        return {
            'modules': self.modules,
            'connections': self.connections,
            'errors': self.errors,
            'success': len(self.errors) == 0,
        }

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_module(self, line: str, line_num: int):
        """Parse: Module: Name (type: category)"""
        try:
            content = re.sub(r'^module:\s*', '', line, flags=re.IGNORECASE)
            name_match = re.match(r'([^(]+)', content)
            if not name_match:
                self.errors.append(f"Line {line_num}: Invalid module format")
                return

            name = name_match.group(1).strip()
            type_match = re.search(r'\(type:\s*(\w+)\)', content, re.IGNORECASE)
            module_type = type_match.group(1).lower() if type_match else 'generic'

            self.modules.append({'name': name, 'type': module_type})
        except Exception as e:
            self.errors.append(f"Line {line_num}: Error parsing module - {e}")

    def _parse_connection(self, line: str, line_num: int):
        """Parse: Connect: Module_A -> Module_B [type]"""
        try:
            content = re.sub(r'^connect:\s*', '', line, flags=re.IGNORECASE)

            if '->' not in content:
                self.errors.append(f"Line {line_num}: Missing '->' in connection")
                return

            # Extract optional [type] at the end
            conn_type = ''
            type_match = re.search(r'\[(\w+)\]\s*$', content)
            if type_match:
                conn_type = type_match.group(1).lower()
                content = content[:type_match.start()].strip()

            parts = content.split('->')
            if len(parts) != 2:
                self.errors.append(f"Line {line_num}: Invalid connection format")
                return

            from_module = parts[0].strip()
            to_module = parts[1].strip()

            if not from_module or not to_module:
                self.errors.append(f"Line {line_num}: Empty module name in connection")
                return

            self.connections.append({
                'from': from_module,
                'to': to_module,
                'type': conn_type,
            })
        except Exception as e:
            self.errors.append(f"Line {line_num}: Error parsing connection - {e}")

    # ------------------------------------------------------------------
    # DOT generation
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_id(name: str) -> str:
        """Convert a module name into a DOT-safe identifier."""
        return (
            name.replace(' ', '_')
                .replace('(', '')
                .replace(')', '')
                .replace(',', '')
                .replace('/', '_')
                .replace('.', '_')
        )

    def build_dot_diagram(self, parsed_data: Dict[str, Any]) -> str:
        """Build a styled DOT diagram from parsed data."""
        if not parsed_data['success']:
            return self._build_error_diagram(parsed_data['errors'])

        modules = parsed_data['modules']
        connections = parsed_data['connections']

        dot = [
            'digraph G {',
            '  rankdir=LR;',
            '  bgcolor="white";',
            '  pad=0.5;',
            '  nodesep=0.6;',
            '  ranksep=1.0;',
            '',
            '  // Global node defaults',
            '  node [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=11, penwidth=1.2];',
            '  edge [fontname="Helvetica", fontsize=9];',
            '',
        ]

        # Nodes
        for module in modules:
            name = module['name']
            sid = self._safe_id(name)
            mtype = module['type']
            color = NODE_COLORS.get(mtype, DEFAULT_NODE_COLOR)
            label = name.replace('_', '\\n', 1)  # break first underscore to 2 lines
            dot.append(
                f'  "{sid}" [label="{label}", fillcolor="{color}"];'
            )

        dot.append('')

        # Edges
        for conn in connections:
            src = self._safe_id(conn['from'])
            dst = self._safe_id(conn['to'])
            ctype = conn.get('type', '')
            style_def = EDGE_STYLES.get(ctype, DEFAULT_EDGE_STYLE)

            attrs = [
                f'color="{style_def["color"]}"',
                f'style="{style_def["style"]}"',
            ]
            if style_def.get("label"):
                attrs.append(f'label="{style_def["label"]}"')
                attrs.append(f'fontcolor="{style_def["color"]}"')

            dot.append(f'  "{src}" -> "{dst}" [{", ".join(attrs)}];')

        # Legend (small table at bottom)
        dot.append('')
        dot.append('  // Legend')
        dot.append('  subgraph cluster_legend {')
        dot.append('    label="Connection Types";')
        dot.append('    style=dashed; fontname="Helvetica"; fontsize=10; color=grey;')
        legend_entries = []
        # Only include types that appear in this diagram
        used_types = {c.get('type', '') for c in connections} - {''}
        for ctype in sorted(used_types):
            if ctype in EDGE_STYLES:
                s = EDGE_STYLES[ctype]
                legend_entries.append(f'{s["label"]}={ctype}')
        if legend_entries:
            legend_text = '  |  '.join(legend_entries)
            dot.append(f'    legend_node [shape=note, style=filled, fillcolor=white, '
                        f'fontsize=9, label="{legend_text}"];')
        dot.append('  }')

        dot.append('}')
        return '\n'.join(dot)

    @staticmethod
    def _build_error_diagram(errors: List[str]) -> str:
        error_text = '\\n'.join(errors[:3])
        return (
            'digraph G {\n'
            '  rankdir=LR;\n'
            '  node[shape=box,style=filled,fillcolor=lightcoral];\n'
            f'  "Error"[label="Diagram Parse Error:\\n{error_text}"];\n'
            '}'
        )


def parse_diagram_text(text: str) -> Tuple[str, List[str]]:
    """Parse diagram text and return (dot_string, errors)."""
    parser = DiagramTextParser()
    parsed = parser.parse(text)
    dot = parser.build_dot_diagram(parsed)
    return dot, parsed['errors']
