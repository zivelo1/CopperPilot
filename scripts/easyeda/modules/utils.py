# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Utilities for EasyEDA converter modules."""
import hashlib
import json
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Point:
    """2D point with EasyEDA coordinate system (10 units = 1mm)."""
    x: float
    y: float

    def to_easyeda(self) -> str:
        """Convert to EasyEDA coordinate string."""
        return f"{self.x:.1f} {self.y:.1f}"

    def offset(self, dx: float, dy: float) -> 'Point':
        """Return new point offset by dx, dy."""
        return Point(self.x + dx, self.y + dy)

@dataclass
class EasyEDAContext:
    """Context object passed through pipeline stages."""
    # Input data
    input_path: Path = None
    output_path: Path = None
    circuits: List[Dict] = field(default_factory=list)

    # Processed data
    components: Dict[str, Any] = field(default_factory=dict)
    connections: List[Dict] = field(default_factory=list)
    nets: Dict[str, List] = field(default_factory=dict)

    # EasyEDA specific
    symbols: Dict[str, Dict] = field(default_factory=dict)
    footprints: Dict[str, Dict] = field(default_factory=dict)
    schematic_data: Dict = field(default_factory=dict)
    pcb_data: Dict = field(default_factory=dict)

    # Validation results
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Statistics
    stats: Dict[str, Any] = field(default_factory=dict)

def generate_id(prefix: str = "gge") -> str:
    """Generate unique EasyEDA ID."""
    import time
    import random
    timestamp = int(time.time() * 1000)
    random_num = random.randint(1000, 9999)
    return f"{prefix}{timestamp}{random_num}"

def easyeda_color(color_name: str) -> str:
    """Convert color name to EasyEDA hex format."""
    colors = {
        "red": "#FF0000",
        "green": "#00FF00",
        "blue": "#0000FF",
        "black": "#000000",
        "white": "#FFFFFF",
        "yellow": "#FFFF00",
        "cyan": "#00FFFF",
        "magenta": "#FF00FF",
        "gray": "#808080",
        "darkgray": "#404040",
        "lightgray": "#C0C0C0",
        "brown": "#8B4513",
        "orange": "#FFA500",
        "purple": "#800080"
    }
    return colors.get(color_name, "#000000")

def mm_to_easyeda(mm: float) -> float:
    """Convert millimeters to EasyEDA units (10 units = 1mm)."""
    return mm * 10

def easyeda_to_mm(units: float) -> float:
    """Convert EasyEDA units to millimeters."""
    return units / 10

def mm_to_mil(mm: float) -> float:
    """Convert millimeters to mil (1 mil = 0.001 inch)."""
    return mm * 39.3700787402

def quantize_mm(value: float, step: float = 0.01) -> float:
    """Quantize a millimeter value to a fixed step (default 0.01mm).

    Rounds to the nearest multiple of `step` to avoid long binary fractions
    that can cause importer normalization overhead. Generic and safe for
    any coordinate or dimension.
    """
    if value is None:
        return value
    try:
        return round(round(value / step) * step, 6)
    except Exception:
        return value

def quantize_point_list(coords: List[float], step: float = 0.01) -> List[float]:
    """Quantize a flat list of coordinates [x1, y1, x2, y2, ...]."""
    out: List[float] = []
    for i, v in enumerate(coords):
        out.append(quantize_mm(v, step))
    return out

def create_bbox(x: float, y: float, width: float, height: float) -> Dict:
    """Create EasyEDA bounding box."""
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height
    }

def rotate_point(point: Point, center: Point, angle: float) -> Point:
    """Rotate point around center by angle (degrees)."""
    import math
    rad = math.radians(angle)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    # Translate to origin
    x = point.x - center.x
    y = point.y - center.y

    # Rotate
    new_x = x * cos_a - y * sin_a
    new_y = x * sin_a + y * cos_a

    # Translate back
    return Point(new_x + center.x, new_y + center.y)

def validate_json_structure(data: Dict) -> Tuple[bool, List[str]]:
    """Validate EasyEDA JSON structure."""
    errors = []

    # Check required top-level fields
    required_fields = ["head", "canvas", "shape"]
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    # Validate head structure
    if "head" in data:
        head = data["head"]
        if not isinstance(head, dict):
            errors.append("'head' must be a dictionary")
        else:
            head_required = ["docType", "editorVersion", "createTime"]
            for field in head_required:
                if field not in head:
                    errors.append(f"Missing head field: {field}")

    # Validate canvas
    if "canvas" in data:
        if not isinstance(data["canvas"], str):
            errors.append("'canvas' must be a string")

    # Validate shapes
    if "shape" in data:
        if not isinstance(data["shape"], list):
            errors.append("'shape' must be a list")

    return len(errors) == 0, errors

def load_config(config_name: str) -> Dict:
    """Load configuration from config directory."""
    config_path = Path(__file__).parent.parent / "config" / f"{config_name}.json"
    if config_path.exists():
        with open(config_path, 'r') as f:
            return json.load(f)
    return {}

def save_json(data: Dict, filepath: Path) -> None:
    """Save JSON with proper formatting."""
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def calculate_net_hash(net_points: List[Tuple[str, str]]) -> str:
    """Calculate hash for net to detect duplicates."""
    sorted_points = sorted(net_points)
    hash_str = json.dumps(sorted_points)
    return hashlib.md5(hash_str.encode()).hexdigest()[:8]
