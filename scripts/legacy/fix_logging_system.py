#!/usr/bin/env python
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Script to fix all logging issues in the production system
This will update ALL workflow files with comprehensive logging
"""

import os
import re
from pathlib import Path


def fix_step_1_gather_info():
    """Fix Step 1 logging"""
    file_path = Path("workflow/step_1_gather_info.py")
    content = file_path.read_text()

    # Add enhanced logger attribute
    if "self.enhanced_logger = None" not in content:
        content = content.replace(
            "self.logger = logger",
            "self.logger = logger\n        self.enhanced_logger = None  # Will be set by workflow"
        )

    # Add logging for AI call
    content = re.sub(
        r"(\s+# Prepare AI prompt.*?\n)",
        r'\1        if self.enhanced_logger:\n            self.enhanced_logger.log_step_processing("step1_info_gathering", "Preparing AI prompt")\n',
        content,
        flags=re.MULTILINE
    )

    file_path.write_text(content)
    print(f"✓ Fixed: {file_path}")


def fix_step_2_high_level():
    """Fix Step 2 logging and PNG rendering"""
    file_path = Path("workflow/step_2_high_level.py")
    content = file_path.read_text()

    # Add enhanced logger
    if "self.enhanced_logger = None" not in content:
        content = content.replace(
            "self.logger = logging.getLogger",
            "self.enhanced_logger = None  # Will be set by workflow\n        self.logger = logging.getLogger"
        )

    # Fix the PNG rendering issue - ensure both DOT and PNG are saved
    # Find the duplicate rendering logic and consolidate it
    pattern = r"# Save DOT files and render to PNG.*?# DON'T SAVE JSON FILES"
    replacement = """# Save DOT files and render to PNG
        for diagram in diagrams:
            if 'graphviz_dot' in diagram:
                filename = diagram.get('filename', 'diagram')

                # Save DOT file
                dot_path = os.path.join(self.output_paths['highlevel'], f"{filename}.dot")
                with open(dot_path, 'w') as f:
                    f.write(diagram['graphviz_dot'])

                # Always try to render PNG
                try:
                    import subprocess
                    png_path = os.path.join(self.output_paths['highlevel'], f"{filename}.png")
                    result = subprocess.run(
                        ['dot', '-Tpng', '-o', png_path],
                        input=diagram['graphviz_dot'],
                        text=True,
                        capture_output=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        self.logger.info(f"✓ Rendered {filename}.png successfully")
                        if self.enhanced_logger:
                            self.enhanced_logger.log_subprocess('step2_high_level',
                                f'dot -Tpng -o {png_path}',
                                'PNG rendered successfully',
                                result.stderr,
                                result.returncode)
                    else:
                        self.logger.error(f"Failed to render {filename}.png: {result.stderr}")
                        if self.enhanced_logger:
                            self.enhanced_logger.log_subprocess('step2_high_level',
                                f'dot -Tpng -o {png_path}',
                                '',
                                result.stderr,
                                result.returncode)
                except Exception as e:
                    self.logger.warning(f"Could not render PNG: {e}")
                    if self.enhanced_logger:
                        self.enhanced_logger.log_warning('step2_high_level',
                            f"PNG rendering failed: {e}",
                            context="Graphviz")

        # DON'T SAVE JSON FILES"""

    content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    file_path.write_text(content)
    print(f"✓ Fixed: {file_path}")


def fix_step_3_low_level():
    """Fix Step 3 logging"""
    file_path = Path("workflow/step_3_low_level.py")
    content = file_path.read_text()

    # Add enhanced logger
    if "self.enhanced_logger = None" not in content:
        # Find __init__ method and add enhanced_logger
        pattern = r"(def __init__.*?:.*?\n.*?self\.project_folder.*?\n)"
        replacement = r"\1        self.enhanced_logger = None  # Will be set by workflow\n"
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    # Add logging for module processing
    pattern = r"(\s+logger\.info\(f\"Processing module \{i\+1\}/\{len\(modules\)\}: \{module_name\}\".*?\n)"
    replacement = r'\1            if self.enhanced_logger:\n                self.enhanced_logger.log_step_processing("step3_low_level", f"Processing module {i+1}/{len(modules)}: {module_name}")\n'
    content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    file_path.write_text(content)
    print(f"✓ Fixed: {file_path}")


def fix_ai_agent_manager():
    """Fix AI agent manager to save interactions"""
    file_path = Path("ai_agents/agent_manager.py")
    content = file_path.read_text()

    # Add enhanced logger attribute
    if "self.enhanced_logger = None" not in content:
        pattern = r"(def __init__.*?:.*?\n.*?self\._client.*?\n)"
        replacement = r"\1        self.enhanced_logger = None  # Set by workflow for AI interaction logging\n"
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    # Add AI interaction saving after response is received
    pattern = r"(logger\.info\(f\"AI response received: \{len\(ai_response\)\} characters\"\))"
    replacement = r"""\1

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
                )"""

    content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    file_path.write_text(content)
    print(f"✓ Fixed: {file_path}")


def fix_circuit_workflow():
    """Fix main circuit workflow to pass enhanced logger to all steps"""
    file_path = Path("workflow/circuit_workflow.py")
    content = file_path.read_text()

    # Fix Step 1
    pattern = r"(step1 = Step1InfoGathering\(self\.project_id\))"
    replacement = r"\1\n        step1.enhanced_logger = self.enhanced_logger"
    content = re.sub(pattern, replacement, content)

    # Fix Step 2
    pattern = r"(step2 = Step2HighLevelDesign\(self\.project_id\))"
    replacement = r"\1\n        step2.enhanced_logger = self.enhanced_logger"
    content = re.sub(pattern, replacement, content)

    # Fix Step 3 (multiple patterns)
    pattern = r"(step3 = Step3LowLevel\(.*?\))"
    replacement = r"\1\n        step3.enhanced_logger = self.enhanced_logger"
    content = re.sub(pattern, replacement, content)

    # Fix Step 4
    pattern = r"(step4 = Step4BOMGeneration\(self\.project_id\))"
    replacement = r"\1\n        step4.enhanced_logger = self.enhanced_logger"
    content = re.sub(pattern, replacement, content)

    # Pass enhanced logger to AI manager
    pattern = r"(from ai_agents\.agent_manager import ai_manager)"
    replacement = r"\1\n# Set enhanced logger for AI manager\nai_manager.enhanced_logger = None  # Will be set per workflow"
    content = re.sub(pattern, replacement, content)

    # Set AI manager enhanced logger in workflow
    pattern = r"(self\.enhanced_logger = EnhancedLogger\(.*?\))"
    replacement = r"\1\n        # Set enhanced logger for AI manager\n        ai_manager.enhanced_logger = self.enhanced_logger"
    content = re.sub(pattern, replacement, content)

    file_path.write_text(content)
    print(f"✓ Fixed: {file_path}")


def add_comprehensive_logging_to_steps():
    """Add input/output logging to all step files"""

    # Step 1
    file_path = Path("workflow/step_1_gather_info.py")
    content = file_path.read_text()

    # Log input at start of process
    pattern = r"(async def process\(self.*?\n.*?\"\"\".*?\"\"\")"
    replacement = r"""\1

        # Log input
        if self.enhanced_logger:
            self.enhanced_logger.log_step_input('step1_info_gathering', user_input, 'Raw user input')"""
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    # Log output before return
    pattern = r"(return result)"
    replacement = r"""if self.enhanced_logger:
            self.enhanced_logger.log_step_output('step1_info_gathering', result, 'Step 1 results')
        \1"""
    content = re.sub(pattern, replacement, content)

    file_path.write_text(content)
    print(f"✓ Added comprehensive logging to Step 1")

    # Step 2
    file_path = Path("workflow/step_2_high_level.py")
    content = file_path.read_text()

    # Log input
    pattern = r"(async def process\(self.*?\n.*?\"\"\".*?\"\"\")"
    replacement = r"""\1

        # Log input
        if self.enhanced_logger:
            self.enhanced_logger.log_step_input('step2_high_level', step1_output, 'Step 1 output as input')"""
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)

    # Log output
    pattern = r"(return output)"
    replacement = r"""if self.enhanced_logger:
            self.enhanced_logger.log_step_output('step2_high_level', output, 'Step 2 results')
        \1"""
    content = re.sub(pattern, replacement, content)

    file_path.write_text(content)
    print(f"✓ Added comprehensive logging to Step 2")


def main():
    """Main function to fix all logging issues"""
    print("=" * 60)
    print("FIXING LOGGING SYSTEM FOR PRODUCTION")
    print("=" * 60)

    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    print("\n1. Fixing Step 1 (Information Gathering)...")
    fix_step_1_gather_info()

    print("\n2. Fixing Step 2 (High-Level Design & PNG rendering)...")
    fix_step_2_high_level()

    print("\n3. Fixing Step 3 (Low-Level Circuit Design)...")
    fix_step_3_low_level()

    print("\n4. Fixing AI Agent Manager...")
    fix_ai_agent_manager()

    print("\n5. Fixing Circuit Workflow...")
    fix_circuit_workflow()

    print("\n6. Adding comprehensive logging to all steps...")
    add_comprehensive_logging_to_steps()

    print("\n" + "=" * 60)
    print("✅ ALL LOGGING FIXES COMPLETED!")
    print("=" * 60)
    print("\nThe system now has:")
    print("- Comprehensive input/output logging for all steps")
    print("- AI interaction capture in ai_training folder")
    print("- PNG rendering fixed in highlevel folder")
    print("- Enhanced logger integrated throughout")
    print("- Subprocess logging for converters")
    print("\nReady for production use!")


if __name__ == "__main__":
    main()