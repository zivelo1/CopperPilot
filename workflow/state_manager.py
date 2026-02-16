# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Workflow State Manager
Replaces N8N's $getWorkflowStaticData functionality
Manages state across workflow steps
"""
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import threading

from utils.logger import setup_logger

logger = setup_logger(__name__)


class WorkflowStateManager:
    """
    Singleton state manager for workflow execution
    Replaces N8N's static data functionality
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(WorkflowStateManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.states = {}  # project_id -> state
        self.current_project_id = None
        
    def initialize_project(self, project_id: str) -> None:
        """Initialize state for a new project"""
        self.current_project_id = project_id
        self.states[project_id] = {
            'project_id': project_id,
            'started_at': datetime.now().isoformat(),
            'results': [],  # Module results from Step 3
            'bom_data': {
                'parts': [],
                'suppliers': {
                    'digikey': [],
                    'mouser': [],
                    'lcsc': []
                },
                'alternatives': {},
                'totals': {
                    'unique_parts': 0,
                    'total_components': 0,
                    'estimated_cost': 0
                }
            },
            'api_cache': {},  # Cache API responses
            'current_step': 0,
            'total_steps': 7,  # 1-Info, 2-HighLevel, 3-Circuits, 4-Conversion, 5-BOM, 6-QA, 7-Package
            'modules': [],  # List of modules to process
            'current_module_index': 0,
            'errors': [],
            'warnings': [],
            'metadata': {}
        }
        logger.info(f"Initialized state for project {project_id}")
    
    def get_state(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Get state for a project"""
        pid = project_id or self.current_project_id
        if pid not in self.states:
            self.initialize_project(pid)
        return self.states[pid]
    
    def update_state(self, key: str, value: Any, project_id: Optional[str] = None) -> None:
        """Update a specific key in the state"""
        state = self.get_state(project_id)
        state[key] = value
        logger.debug(f"Updated state key '{key}' for project {project_id or self.current_project_id}")
    
    def append_result(self, result: Dict, project_id: Optional[str] = None) -> None:
        """Append a result to the results list"""
        state = self.get_state(project_id)
        state['results'].append(result)
        logger.info(f"Appended result for module {result.get('module', 'unknown')}")
    
    def get_results(self, project_id: Optional[str] = None) -> List[Dict]:
        """Get all results for a project"""
        state = self.get_state(project_id)
        return state.get('results', [])
    
    def update_bom_data(self, bom_update: Dict, project_id: Optional[str] = None) -> None:
        """Update BOM data"""
        state = self.get_state(project_id)
        bom_data = state.get('bom_data', {})
        
        # Merge the update
        for key, value in bom_update.items():
            if key in bom_data:
                if isinstance(value, dict) and isinstance(bom_data[key], dict):
                    bom_data[key].update(value)
                elif isinstance(value, list) and isinstance(bom_data[key], list):
                    bom_data[key].extend(value)
                else:
                    bom_data[key] = value
            else:
                bom_data[key] = value
        
        state['bom_data'] = bom_data
        logger.debug("Updated BOM data")
    
    def cache_api_response(self, cache_key: str, response: Any, project_id: Optional[str] = None) -> None:
        """Cache an API response"""
        state = self.get_state(project_id)
        state['api_cache'][cache_key] = {
            'response': response,
            'cached_at': datetime.now().isoformat()
        }
        logger.debug(f"Cached API response for key: {cache_key}")
    
    def get_cached_response(self, cache_key: str, project_id: Optional[str] = None) -> Optional[Any]:
        """Get a cached API response"""
        state = self.get_state(project_id)
        cached = state['api_cache'].get(cache_key)
        if cached:
            logger.debug(f"Found cached response for key: {cache_key}")
            return cached['response']
        return None
    
    def increment_module_index(self, project_id: Optional[str] = None) -> int:
        """Increment and return the current module index"""
        state = self.get_state(project_id)
        state['current_module_index'] += 1
        return state['current_module_index']
    
    def get_current_module_index(self, project_id: Optional[str] = None) -> int:
        """Get the current module index"""
        state = self.get_state(project_id)
        return state.get('current_module_index', 0)
    
    def set_modules(self, modules: List[str], project_id: Optional[str] = None) -> None:
        """Set the list of modules to process"""
        state = self.get_state(project_id)
        state['modules'] = modules
        state['current_module_index'] = 0
        logger.info(f"Set {len(modules)} modules to process")
    
    def get_modules(self, project_id: Optional[str] = None) -> List[str]:
        """Get the list of modules"""
        state = self.get_state(project_id)
        return state.get('modules', [])
    
    def add_error(self, error: str, context: Optional[Dict] = None, project_id: Optional[str] = None) -> None:
        """Add an error to the state"""
        state = self.get_state(project_id)
        error_entry = {
            'message': error,
            'timestamp': datetime.now().isoformat(),
            'context': context or {}
        }
        state['errors'].append(error_entry)
        logger.error(f"Error recorded: {error}")
    
    def add_warning(self, warning: str, context: Optional[Dict] = None, project_id: Optional[str] = None) -> None:
        """Add a warning to the state"""
        state = self.get_state(project_id)
        warning_entry = {
            'message': warning,
            'timestamp': datetime.now().isoformat(),
            'context': context or {}
        }
        state['warnings'].append(warning_entry)
        logger.warning(f"Warning recorded: {warning}")
    
    def update_progress(self, step: int, project_id: Optional[str] = None) -> None:
        """Update workflow progress"""
        state = self.get_state(project_id)
        state['current_step'] = step
        progress = (step / state['total_steps']) * 100
        logger.info(f"Progress: Step {step}/{state['total_steps']} ({progress:.1f}%)")
    
    def save_to_file(self, filepath: Path, project_id: Optional[str] = None) -> None:
        """Save state to a JSON file"""
        state = self.get_state(project_id)
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        logger.info(f"State saved to {filepath}")
    
    def load_from_file(self, filepath: Path, project_id: str) -> None:
        """Load state from a JSON file"""
        with open(filepath, 'r') as f:
            state = json.load(f)
        self.states[project_id] = state
        self.current_project_id = project_id
        logger.info(f"State loaded from {filepath} for project {project_id}")
    
    def clear_project(self, project_id: Optional[str] = None) -> None:
        """Clear state for a project"""
        pid = project_id or self.current_project_id
        if pid in self.states:
            del self.states[pid]
            logger.info(f"Cleared state for project {pid}")
    
    def get_summary(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Get a summary of the current state"""
        state = self.get_state(project_id)
        return {
            'project_id': state['project_id'],
            'started_at': state['started_at'],
            'current_step': state['current_step'],
            'total_steps': state['total_steps'],
            'progress': (state['current_step'] / state['total_steps']) * 100,
            'modules_count': len(state['modules']),
            'modules_processed': state['current_module_index'],
            'results_count': len(state['results']),
            'errors_count': len(state['errors']),
            'warnings_count': len(state['warnings']),
            'cached_responses': len(state['api_cache']),
            'bom_parts': len(state['bom_data']['parts'])
        }


# Create singleton instance
state_manager = WorkflowStateManager()


class ModuleIteratorState:
    """
    Helper class for module iteration state
    Used by Step 3 workflow
    """
    
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.state_manager = state_manager
        
    def initialize(self, modules: List[Dict]) -> None:
        """Initialize module iteration"""
        module_names = [m.get('module', f'Module_{i}') for i, m in enumerate(modules)]
        self.state_manager.set_modules(module_names, self.project_id)
        self.state_manager.update_state('module_details', modules, self.project_id)
        
    def get_current_index(self) -> int:
        """Get current module index"""
        return self.state_manager.get_current_module_index(self.project_id)
    
    def increment(self) -> int:
        """Increment and return new index"""
        return self.state_manager.increment_module_index(self.project_id)
    
    def store_result(self, module_name: str, circuit: Dict) -> None:
        """Store module result"""
        result = {
            'module': module_name,
            'index': self.get_current_index(),
            'design': circuit,
            'timestamp': datetime.now().isoformat()
        }
        self.state_manager.append_result(result, self.project_id)
    
    def get_results(self) -> List[Dict]:
        """Get all stored results"""
        return self.state_manager.get_results(self.project_id)
    
    def has_more(self) -> bool:
        """Check if more modules to process"""
        modules = self.state_manager.get_modules(self.project_id)
        current = self.get_current_index()
        return current < len(modules)
