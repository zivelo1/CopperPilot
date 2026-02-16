# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 6: Final Packaging
Packages all outputs into a downloadable ZIP file

Professional notes (generic, modular, and non-user-facing artifacts):
- The user requested that internal manifests not be delivered to end users.
- We therefore relocate the run manifest to `project_info/manifest.json` and
  exclude it from the downloadable package while keeping it available for
  internal tooling and logs.
- The legacy run-level README.md is deprecated; we stop generating it to avoid
  redundancy with `project_info/project_summary.pdf`.
"""

import json
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# NEW: Generate Assembly Guide before packaging
try:
    from workflow.generate_assembly_guide import AssemblyGuideGenerator
    HAS_ASSEMBLY_GEN = True
except ImportError:
    HAS_ASSEMBLY_GEN = False

class Step6FinalPackaging:
    """
    Final packaging of all circuit design outputs
    """

    def __init__(self, project_id: str):
        self.project_id = project_id

    def create_readme(self, output_dir: Path, summary: Dict) -> str | None:
        """Deprecated: Run-level README is no longer generated.

        Rationale:
        - The authoritative human-facing report is `project_info/project_summary.pdf`.
        - Avoids duplicating or diverging information across artifacts.
        - Preserves method signature compatibility by returning None.
        """
        return None

    def _format_circuit_details(self, circuits: List[Dict]) -> str:
        """Format circuit details for README"""
        if not circuits:
            return "No circuit details available"

        details = []
        for circuit in circuits:
            name = circuit.get('name', 'Unknown')
            comp_count = len(circuit.get('components', []))
            net_count = len(circuit.get('nets', []))
            details.append(f"- **{name}**: {comp_count} components, {net_count} nets")

        return '\n'.join(details)

    def create_project_json(self, output_dir: Path, data: Dict) -> str:
        """Create a project metadata JSON file for internal use.

        Professional notes:
        - Manifest is kept for internal tooling/traceability but not shipped to end users.
        - We place it under `project_info/manifest.json` alongside the PDF summary,
          which keeps related artifacts together and out of user packaging.
        """
        project_data = {
            'project_id': self.project_id,
            'generated': datetime.now().isoformat(),
            'version': '1.0.0',
            'generator': 'N8N Electronic Expert',
            'summary': {
                'circuits_count': len(data.get('circuits', [])),
                'total_components': data.get('total_components', 0),
                'total_cost': data.get('total_cost', 0),
                'formats': data.get('formats', [])
            },
            'files': self._list_all_files(output_dir)
        }

        # Write manifest to project_info/manifest.json (ensure directory exists)
        project_info_dir = output_dir / 'project_info'
        project_info_dir.mkdir(parents=True, exist_ok=True)
        json_path = project_info_dir / 'manifest.json'
        with open(json_path, 'w') as f:
            json.dump(project_data, f, indent=2)

        return str(json_path)

    def _list_all_files(self, output_dir: Path) -> Dict[str, List[str]]:
        """List all files in the output directory by category"""
        files = {}

        for subdir in output_dir.iterdir():
            if subdir.is_dir():
                category_files = []
                for file_path in subdir.glob('*'):
                    if file_path.is_file():
                        category_files.append(file_path.name)
                if category_files:
                    files[subdir.name] = sorted(category_files)

        return files

    async def process(self,
                      output_dir: str,
                      circuits: List[Dict],
                      bom_data: Dict,
                      conversion_results: Dict) -> Dict[str, Any]:
        """
        Main processing function for Step 6
        Creates a ZIP package of all outputs
        """
        try:
            output_path = Path(output_dir)

            # Gather summary data
            summary = {
                'circuits': circuits,
                'circuits_count': len(circuits),
                'total_components': bom_data.get('total_components', 0),
                'total_cost': bom_data.get('total_cost', 0),
                'formats': list(conversion_results.keys()) if conversion_results else []
            }

            # README generation is deprecated; keep variable for compatibility
            readme_path = self.create_readme(output_path, summary)

            # Create project metadata
            project_json_path = self.create_project_json(output_path, summary)

            # NEW: Generate Assembly Guide (Step 5.5)
            if HAS_ASSEMBLY_GEN:
                try:
                    print("  📄 Generating Assembly Guide...")
                    generator = AssemblyGuideGenerator(output_path)
                    generator.generate()
                except Exception as e:
                    print(f"  ⚠️  Assembly Guide generation failed: {e}")

            # Create ZIP file
            zip_filename = f"{self.project_id}_circuit_design.zip"
            zip_path = output_path.parent / zip_filename

            def _excluded(rel: Path) -> bool:
                parts = rel.parts
                # Exclude entire lowlevel directory
                if len(parts) >= 2 and parts[1] == 'lowlevel':
                    return True
                # Exclude verification directory (ALL validation artifacts)
                # Added Oct 27, 2025 - centralized validation results
                if len(parts) >= 2 and parts[1] == 'verification':
                    return True
                # Exclude kicad/ERC and kicad/DRC (legacy locations)
                # Note: ERC/DRC now go to verification/, but keep for backwards compatibility
                if len(parts) >= 3 and parts[1] == 'kicad' and parts[2] in {'ERC', 'DRC'}:
                    return True
                # Exclude eagle/ERC and eagle/DRC (legacy locations)
                # Note: ERC/DRC now go to verification/, but keep for backwards compatibility
                if len(parts) >= 3 and parts[1] == 'eagle' and parts[2] in {'ERC', 'DRC'}:
                    return True
                # Exclude internal QA reports
                if len(parts) >= 2 and parts[1] == 'qa':
                    name = parts[-1]
                    if str(name).startswith('internal_') or str(name) in {'internal_qa_report.json', 'internal_qa_report.html'}:
                        return True
                # Exclude run-level README from package (user gets PDF summary instead)
                if len(parts) >= 2 and parts[1] == 'README.md':
                    return True
                # Exclude internal manifest JSON(s) from project_info directory
                if len(parts) >= 3 and parts[1] == 'project_info' and str(parts[-1]).lower().endswith('.json'):
                    return True
                return False

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add selected files from output directory, excluding specified paths
                for file_path in output_path.rglob('*'):
                    if not file_path.is_file():
                        continue
                    # Build archive path relative to output root parent (to include run folder name)
                    arcname = file_path.relative_to(output_path.parent)
                    # Check exclusions against path relative to output root
                    rel_to_root = file_path.relative_to(output_path.parent / output_path.name)
                    if _excluded(Path(output_path.name) / rel_to_root):
                        continue
                    zipf.write(file_path, arcname)

            # Calculate package size
            package_size = zip_path.stat().st_size

            return {
                'success': True,
                'package_path': str(zip_path),
                'package_size': package_size,
                'package_size_mb': round(package_size / (1024 * 1024), 2),
                'total_files': sum(len(files) for files in self._list_all_files(output_path).values()),
                'readme_path': readme_path,
                'project_json_path': project_json_path,
                'summary': summary
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
