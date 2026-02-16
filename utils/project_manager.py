# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Centralized Project Manager
Ensures consistent project IDs and folder structures across the system
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import uuid


class ProjectManager:
    """
    Singleton manager for project IDs and directory structures.
    Ensures only ONE output folder and ONE logs/runs folder per workflow run.
    """

    _instance = None
    _projects = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ProjectManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self._projects = {}

    def create_project(self, base_id: Optional[str] = None) -> Dict[str, any]:
        """
        Create a new project with unique ID and directory structure.

        Args:
            base_id: Optional base ID to use (will be made unique)

        Returns:
            Dict with project_id, output_dir, logs_dir
        """
        # Generate unique project folder name
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        if base_id:
            # Sanitize base_id to be filesystem safe
            safe_id = base_id[:8] if len(base_id) > 8 else base_id
            safe_id = ''.join(c for c in safe_id if c.isalnum() or c in '-_')
            project_folder = f"{timestamp}-{safe_id}"
        else:
            # Generate random ID
            safe_id = str(uuid.uuid4())[:8]
            project_folder = f"{timestamp}-{safe_id}"

        # Store original project_id (can be different from folder name)
        project_id = base_id or safe_id

        # Create paths (but don't create directories yet)
        output_root = os.environ.get('OUTPUT_ROOT_DIR', 'output')
        output_dir = Path(output_root) / project_folder
        logs_dir = Path('logs') / 'runs' / project_folder

        # Store project info
        project_info = {
            'project_id': project_id,
            'project_folder': project_folder,
            'output_dir': output_dir,
            'logs_dir': logs_dir,
            'timestamp': timestamp,
            'created_at': datetime.now()
        }

        self._projects[project_id] = project_info

        return project_info

    def get_project(self, project_id: str) -> Optional[Dict]:
        """Get project info by ID"""
        return self._projects.get(project_id)

    def ensure_directories(self, project_id: str) -> Dict[str, Path]:
        """
        Create all necessary directories for a project.
        Called only when we're ready to start generating files.
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        output_dir = project['output_dir']
        logs_dir = project['logs_dir']

        # Create output subdirectories
        # Include project_info for human-facing project summary PDFs (Step 2.5)
        # Include spice for SPICE/LTSpice simulation files (December 2025)
        dirs = {
            'output_root': output_dir,
            'highlevel': output_dir / 'highlevel',
            'lowlevel': output_dir / 'lowlevel',
            'kicad': output_dir / 'kicad',
            'eagle': output_dir / 'eagle',
            'easyeda_pro': output_dir / 'easyeda_pro',
            'schematics': output_dir / 'schematics',
            'schematics_desc': output_dir / 'schematics_desc',
            'bom': output_dir / 'bom',
            'project_info': output_dir / 'project_info',
            'spice': output_dir / 'spice',  # SPICE/LTSpice simulation files
        }

        # Create logs subdirectories
        logs_dirs = {
            'logs_root': logs_dir,
            'steps': logs_dir / 'steps',
            'ai_training': logs_dir / 'ai_training'
        }

        # Create all directories
        for dir_path in dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)

        for dir_path in logs_dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)

        # Return all paths
        all_dirs = {**dirs, **logs_dirs}
        return all_dirs

    @classmethod
    def reset(cls):
        """Reset the singleton (mainly for testing)"""
        cls._instance = None


# Global instance
project_manager = ProjectManager()
