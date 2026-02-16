# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Utilities for schematic generator modules."""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set, Any
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

@dataclass
class Point:
    """2D point for schematic coordinates."""
    x: int
    y: int

    def distance_to(self, other: 'Point') -> float:
        """Calculate distance to another point."""
        return math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)

    def __hash__(self):
        return hash((self.x, self.y))

@dataclass
class Rectangle:
    """Rectangle for component bounds."""
    x: int
    y: int
    width: int
    height: int

    def contains(self, point: Point) -> bool:
        """Check if point is within rectangle."""
        return (self.x <= point.x <= self.x + self.width and
                self.y <= point.y <= self.y + self.height)

    def intersects(self, other: 'Rectangle') -> bool:
        """
        Check if rectangles intersect.
        """
        return not (self.x + self.width < other.x or
                   other.x + other.width < self.x or
                   self.y + self.height < other.y or
                   other.y + other.height < self.y)

    @property
    def center(self) -> Point:
        """Get center point of rectangle."""
        return Point(self.x + self.width // 2, self.y + self.height // 2)

@dataclass
class Pin:
    """Component pin definition."""
    number: str
    name: str
    position: Point
    type: str = 'passive'  # passive, input, output, power, ground, unconnected
    component_ref: str = ''

    def __hash__(self):
        return hash((self.component_ref, self.number))

@dataclass
class Component:
    """Component definition for schematic."""
    ref_des: str
    type: str
    value: str
    position: Point
    bounds: Rectangle
    pins: Dict[str, Pin] = field(default_factory=dict)
    symbol: str = 'generic'
    rotation: int = 0  # 0, 90, 180, 270 degrees
    specs: Dict[str, Any] = field(default_factory=dict)

    def get_pin(self, pin_number: str) -> Optional[Pin]:
        """Get pin by number."""
        return self.pins.get(pin_number)

    def add_pin(self, pin_number: str, name: str, position: Point, pin_type: str = 'passive'):
        """Add a pin to the component."""
        self.pins[pin_number] = Pin(
            number=pin_number,
            name=name,
            position=position,
            type=pin_type,
            component_ref=self.ref_des
        )

@dataclass
class Wire:
    """Wire segment for connections."""
    start: Point
    end: Point
    net: str
    color: str = 'black'
    width: int = 2

    def to_rectangle(self) -> Rectangle:
        """Returns the bounding box of the wire segment."""
        min_x = min(self.start.x, self.end.x)
        max_x = max(self.start.x, self.end.x)
        min_y = min(self.start.y, self.end.y)
        max_y = max(self.start.y, self.end.y)
        return Rectangle(min_x, min_y, max_x - min_x, max_y - min_y)

@dataclass
class Net:
    """Net definition connecting multiple pins."""
    name: str
    pins: List[Tuple[str, str]] = field(default_factory=list)  # [(component_ref, pin_number)]
    color: str = 'black'
    is_power: bool = False
    is_ground: bool = False

    def add_connection(self, component_ref: str, pin_number: str):
        """Add a connection to the net."""
        self.pins.append((component_ref, pin_number))

@dataclass
class SchematicContext:
    """Context object passed through pipeline stages."""
    # Input data
    input_path: Path = None
    output_path: Path = None
    circuit_data: Dict = field(default_factory=dict)

    # Processed data
    components: Dict[str, Component] = field(default_factory=dict)
    nets: Dict[str, Net] = field(default_factory=dict)
    wires: List[Wire] = field(default_factory=list)
    pin_number_to_name: Dict[str, str] = field(default_factory=dict)  # Map "Q1.1" -> "Q1.G"

    # Drawing context
    image: Image.Image = None
    draw: ImageDraw.Draw = None
    font: ImageFont.ImageFont = None
    font_small: ImageFont.ImageFont = None

    # Layout information
    canvas_width: int = 3600
    canvas_height: int = 2400
    grid_size: int = 10
    component_spacing_x: int = 350
    component_spacing_y: int = 280

    # Validation results
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Statistics
    stats: Dict[str, Any] = field(default_factory=dict)

def get_wire_color(net_name: str) -> str:
    """Get wire color based on net name."""
    net_lower = net_name.lower()

    # Power nets - red
    if any(pwr in net_lower for pwr in ['vcc', 'vdd', 'v+', '+5v', '+3.3v', '+12v', '+15v', '+24v', 'vin']):
        return 'red'

    # Ground nets - black
    if any(gnd in net_lower for gnd in ['gnd', 'ground', 'vss', 'v-', '0v', 'dgnd', 'agnd']):
        return 'black'

    # Clock signals - blue
    if any(clk in net_lower for clk in ['clk', 'clock', 'xtal', 'osc']):
        return 'blue'

    # Data signals - green
    if any(data in net_lower for data in ['data', 'sda', 'scl', 'mosi', 'miso', 'tx', 'rx', 'uart']):
        return 'green'

    # Reset/control - orange
    if any(ctrl in net_lower for ctrl in ['rst', 'reset', 'enable', 'cs', 'ss']):
        return 'orange'

    # Default - dark gray
    return 'darkgray'

def parse_pin_reference(pin_ref: str) -> Tuple[str, str]:
    """Parse component.pin reference into component and pin."""
    if '.' in pin_ref:
        parts = pin_ref.split('.', 1)
        return parts[0], parts[1]
    return pin_ref, '1'

def manhattan_distance(p1: Point, p2: Point) -> int:
    """Calculate Manhattan distance between two points."""
    return abs(p1.x - p2.x) + abs(p1.y - p2.y)

def get_component_type_category(comp_type: str) -> str:
    """Categorize component type for layout grouping."""
    comp_lower = comp_type.lower()

    if any(x in comp_lower for x in ['connector', 'jack', 'plug', 'terminal']):
        return 'connector'
    elif any(x in comp_lower for x in ['ic', 'chip', 'microcontroller', 'mcu', 'cpu']):
        return 'ic'
    elif any(x in comp_lower for x in ['transistor', 'mosfet', 'bjt', 'fet', 'jfet']):
        return 'transistor'
    elif any(x in comp_lower for x in ['resistor', 'res', 'r_']):
        return 'resistor'
    elif any(x in comp_lower for x in ['capacitor', 'cap', 'c_']):
        return 'capacitor'
    elif any(x in comp_lower for x in ['inductor', 'coil', 'l_', 'transformer']):
        return 'inductor'
    elif any(x in comp_lower for x in ['diode', 'led', 'd_', 'rectifier', 'zener']):
        return 'diode'
    elif any(x in comp_lower for x in ['crystal', 'xtal', 'oscillator']):
        return 'crystal'
    elif any(x in comp_lower for x in ['switch', 'button', 'relay']):
        return 'switch'
    elif any(x in comp_lower for x in ['fuse', 'breaker']):
        return 'fuse'
    else:
        return 'misc'

def line_segment_intersects_rectangle(p1: Point, p2: Point, rect: Rectangle) -> bool:
    """
    Checks if a line segment (p1, p2) intersects with a rectangle.
    Uses Liang-Barsky algorithm principles.
    """
    min_x, max_x = rect.x, rect.x + rect.width
    min_y, max_y = rect.y, rect.y + rect.height

    dx = p2.x - p1.x
    dy = p2.y - p1.y

    p = [0.0] * 4
    q = [0.0] * 4

    p[0], q[0] = -dx, -(min_x - p1.x)
    p[1], q[1] = dx, (max_x - p1.x)
    p[2], q[2] = -dy, -(min_y - p1.y)
    p[3], q[3] = dy, (max_y - p1.y)

    u1, u2 = 0.0, 1.0

    for i in range(4):
        if p[i] == 0:
            if q[i] < 0:
                # Line is parallel to clipping edge and outside
                return False
        else:
            t = q[i] / p[i]
            if p[i] < 0:
                u1 = max(u1, t)
            else:
                u2 = min(u2, t)

    if u1 > u2:
        return False
    
    # Check if endpoints are inside the rectangle (handles cases where line segment is fully contained)
    if rect.contains(p1) or rect.contains(p2):
        return True

    return True # Intersection found and not fully contained


def line_segment_crosses_rectangle_body(p1: Point, p2: Point, rect: Rectangle) -> bool:
    """
    Checks if a line segment (p1, p2) strictly crosses the *body* of a rectangle.
    It returns true if any part of the line segment is inside the rectangle, but not just on the boundary.
    This also means the endpoints themselves should not be considered "inside" if they fall exactly on the perimeter.
    """
    # Check if both endpoints are strictly inside the rectangle. If so, it crosses.
    if (rect.x < p1.x < rect.x + rect.width and rect.y < p1.y < rect.y + rect.height and
        rect.x < p2.x < rect.x + rect.width and rect.y < p2.y < rect.y + rect.height):
        return True

    # Check if one endpoint is strictly inside and the other is outside. If so, it crosses.
    p1_inside = rect.x < p1.x < rect.x + rect.width and rect.y < p1.y < rect.y + rect.height
    p2_inside = rect.x < p2.x < rect.x + rect.width and rect.y < p2.y < rect.y + rect.height

    if (p1_inside and not p2_inside) or (p2_inside and not p1_inside):
        return True
    
    # Check if the line segment intersects any of the four sides of the rectangle
    # excluding endpoints for "crossing" vs "touching"
    
    # Coordinates of rectangle corners
    r_x1, r_y1 = rect.x, rect.y
    r_x2, r_y2 = rect.x + rect.width, rect.y + rect.height

    # Helper function for line-line intersection
    def _line_line_intersection(l1_p1, l1_p2, l2_p1, l2_p2):
        x1, y1 = l1_p1.x, l1_p1.y
        x2, y2 = l1_p2.x, l1_p2.y
        x3, y3 = l2_p1.x, l2_p1.y
        x4, y4 = l2_p2.x, l2_p2.y

        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if den == 0:
            return None # Lines are parallel or collinear

        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den

        if 0 < t < 1 and 0 < u < 1: # Strict intersection (not at endpoints)
            return Point(int(x1 + t * (x2 - x1)), int(y1 + t * (y2 - y1)))
        return None

    # Check intersection with each side of the rectangle
    rect_sides = [
        (Point(r_x1, r_y1), Point(r_x2, r_y1)), # Top
        (Point(r_x2, r_y1), Point(r_x2, r_y2)), # Right
        (Point(r_x2, r_y2), Point(r_x1, r_y2)), # Bottom
        (Point(r_x1, r_y2), Point(r_x1, r_y1))  # Left
    ]

    for rect_p1, rect_p2 in rect_sides:
        if _line_line_intersection(p1, p2, rect_p1, rect_p2):
            return True # Found a strict intersection with a side

    return False


def load_config(config_name: str) -> Dict:
    """Load configuration from config directory."""
    config_path = Path(__file__).parent.parent / 'config' / f'{config_name}.json'
    if config_path.exists():
        import json
        with open(config_path, 'r') as f:
            return json.load(f)
    return {}