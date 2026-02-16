# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Celery tasks for background circuit generation
"""
import json
import asyncio
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

from celery import Task
from celery_app import celery_app
from workflow.circuit_workflow import CircuitWorkflow
from utils.logger import setup_logger

logger = setup_logger(__name__)


class CallbackTask(Task):
    """Task with callbacks for progress updates"""

    def on_success(self, retval, task_id, args, kwargs):
        """Called on successful completion"""
        logger.info(f"Task {task_id} completed successfully")

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called on task failure"""
        logger.error(f"Task {task_id} failed: {exc}")


@celery_app.task(bind=True, base=CallbackTask, name='workflow.generate_circuit')
def generate_circuit(self, project_id: str, requirements: Dict) -> Dict:
    """
    Main task to generate circuit from requirements
    Runs the complete workflow with progress updates
    """
    import requests

    def send_ws_update(update):
        """Send WebSocket update through server"""
        try:
            requests.post(
                f'http://localhost:8000/internal/ws-update/{project_id}',
                json=update
            )
        except Exception as e:
            logger.error(f"Failed to send WS update: {e}")

    try:
        logger.info(f"Starting circuit generation for project {project_id}")

        # Create workflow instance
        workflow = CircuitWorkflow(project_id)

        # Run workflow with progress updates
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_with_updates():
            # Step 1: Information Gathering
            self.update_state(state='PROGRESS', meta={'current': 1, 'total': 6, 'status': 'Information Gathering'})
            send_ws_update({'type': 'progress', 'step': 1, 'progress': 0, 'status': 'Information Gathering', 'eta': '5:00'})

            step1_result = await workflow.step_1_gather_info(requirements)
            await asyncio.sleep(2)

            # Step 2: High-Level Design
            self.update_state(state='PROGRESS', meta={'current': 2, 'total': 6, 'status': 'High-Level Design'})
            send_ws_update({'type': 'progress', 'step': 2, 'progress': 17, 'status': 'High-Level Design', 'eta': '4:00'})

            step2_result = await workflow.step_2_high_level(step1_result)
            await asyncio.sleep(3)

            # Step 3: Circuit Generation
            self.update_state(state='PROGRESS', meta={'current': 3, 'total': 6, 'status': 'Circuit Generation'})
            send_ws_update({'type': 'progress', 'step': 3, 'progress': 34, 'status': 'Circuit Generation', 'eta': '3:00'})

            circuits = await workflow.step_3_low_level(step2_result)
            await asyncio.sleep(4)

            # Step 4: BOM Generation
            self.update_state(state='PROGRESS', meta={'current': 4, 'total': 6, 'status': 'BOM Generation'})
            send_ws_update({'type': 'progress', 'step': 4, 'progress': 50, 'status': 'BOM Generation', 'eta': '2:00'})

            bom = await workflow.step_4_bom(circuits)
            await asyncio.sleep(2)

            # Step 5: Format Conversion
            self.update_state(state='PROGRESS', meta={'current': 5, 'total': 6, 'status': 'Format Conversion'})
            send_ws_update({'type': 'progress', 'step': 5, 'progress': 67, 'status': 'Format Conversion', 'eta': '1:00'})

            conversions = await workflow.step_5_convert(circuits)
            await asyncio.sleep(3)

            # Step 6: Quality Check
            self.update_state(state='PROGRESS', meta={'current': 6, 'total': 6, 'status': 'Quality Check'})
            send_ws_update({'type': 'progress', 'step': 6, 'progress': 84, 'status': 'Quality Check', 'eta': '0:30'})

            qa = await workflow.step_6_qa(circuits, conversions)
            await asyncio.sleep(1)

            # Complete
            send_ws_update({'type': 'complete', 'progress': 100, 'status': 'Complete',
                           'message': 'Circuit generation completed!',
                           'output_dir': str(workflow.output_dir)})

            return {
                'success': True,
                'circuits': circuits,
                'bom': bom,
                'conversions': conversions,
                'output_dir': str(workflow.output_dir)
            }

        try:
            result = loop.run_until_complete(run_with_updates())
        finally:
            loop.close()

        logger.info(f"Circuit generation completed for project {project_id}")

        return {
            'project_id': project_id,
            'success': True,
            'output_dir': str(workflow.output_dir),
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error in circuit generation: {e}")
        raise


@celery_app.task(name='workflow.fix_circuit')
def fix_circuit(circuit: Dict) -> Dict:
    """
    Task to fix circuit issues
    High priority task for quick fixes
    """
    try:
        from workflow.step_3_low_level import fix_net_conflicts
        from workflow.safety_net_validator import safety_net_validator

        logger.info("Fixing circuit issues...")

        # Apply fixes
        fixed = fix_net_conflicts(circuit)
        validated = safety_net_validator(fixed)

        return validated

    except Exception as e:
        logger.error(f"Error fixing circuit: {e}")
        raise


@celery_app.task(name='workflow.convert_format')
def convert_format(project_folder: str, format_type: str) -> Dict:
    """
    Task to convert circuit to specific format
    Runs converter scripts
    """
    try:
        import subprocess
        from server.config import config

        logger.info(f"Converting to {format_type} format...")

        # Map format to converter script
        converters = {
            'kicad': 'kicad_converter.py',
            'eagle': 'eagle_converter.py',
            'easyeda_pro': 'easyeda_converter_pro.py',
            'schematics': 'schematics_converter.py',
            'text': 'schematics_text_converter.py'
        }

        if format_type not in converters:
            raise ValueError(f"Unknown format: {format_type}")

        script_name = converters[format_type]
        script_path = config.SCRIPTS_DIR / script_name

        if not script_path.exists():
            raise FileNotFoundError(f"Converter script not found: {script_path}")

        # Prepare paths
        input_dir = config.OUTPUT_DIR / project_folder / "lowlevel"
        output_dir = config.OUTPUT_DIR / project_folder / format_type

        # Run converter
        cmd = [
            'python3',
            str(script_path),
            str(input_dir),
            str(output_dir)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Converter failed: {result.stderr}")
            return {
                'success': False,
                'format': format_type,
                'error': result.stderr
            }

        # List output files
        output_files = list(output_dir.glob('*'))

        return {
            'success': True,
            'format': format_type,
            'output_dir': str(output_dir),
            'files': [str(f.name) for f in output_files],
            'count': len(output_files)
        }

    except Exception as e:
        logger.error(f"Error in format conversion: {e}")
        return {
            'success': False,
            'format': format_type,
            'error': str(e)
        }


@celery_app.task(name='workflow.validate_circuit')
def validate_circuit_task(circuit: Dict) -> Dict:
    """
    Task to validate a circuit
    """
    try:
        from workflow.step_3_low_level import validate_circuit

        logger.info("Validating circuit...")

        validation = validate_circuit(circuit)

        return validation

    except Exception as e:
        logger.error(f"Error validating circuit: {e}")
        return {
            'valid': False,
            'error': str(e)
        }


@celery_app.task(name='workflow.cleanup_old_projects')
def cleanup_old_projects() -> Dict:
    """
    Periodic task to clean up old project files
    Runs hourly via beat schedule
    """
    try:
        from server.config import config
        import shutil

        logger.info("Cleaning up old projects...")

        cutoff_date = datetime.now().timestamp() - (7 * 24 * 60 * 60)  # 7 days
        cleaned = 0

        for project_dir in config.OUTPUT_DIR.glob('*'):
            if project_dir.is_dir():
                # Check creation time
                if project_dir.stat().st_mtime < cutoff_date:
                    logger.info(f"Removing old project: {project_dir.name}")
                    shutil.rmtree(project_dir)
                    cleaned += 1

        logger.info(f"Cleaned up {cleaned} old projects")

        return {
            'success': True,
            'cleaned': cleaned,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error in cleanup: {e}")
        return {
            'success': False,
            'error': str(e)
        }