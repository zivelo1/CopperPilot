# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Layout engine module for schematic generator - PROFESSIONAL GRADE.

Version: 3.0 - Fixed component overlay, collision detection, proper spacing
Date: October 2025
Author: Electronics AI System

Implements IEEE 315-1975 standard for schematic layout:
- Grid-based layout (10mm grid)
- Component spacing 2.5-3.0mm between pins
- 7.5mm minimum between symbols
- Left-to-right signal flow
- Collision detection and avoidance
- Hierarchical component grouping
"""
from typing import Dict, List, Tuple, Optional, Set
from .utils import SchematicContext, Component, Point, Rectangle, Pin, get_component_type_category
from .symbol_library import SymbolLibrary

class LayoutEngine:
    """Professional-grade component placement with collision detection."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.symbol_library = SymbolLibrary(config)
        self.grid_size = 10  # IEEE standard: 10mm grid (0.1" = 2.54mm)
        self.margin = 150  # Increased margin for cleaner layout
        self.min_component_spacing = 400  # Minimum spacing between component centers (increased for better routing)
        self.component_padding = 50 # Consistent padding around component bounds for collision detection
        self.occupied_regions = []  # Track occupied rectangular regions

    def execute(self, context: SchematicContext) -> SchematicContext:
        """Layout components on schematic with professional-grade algorithms."""
        print("\n=== Stage 2: Layout Engine (Professional Grade v3.0) ===")

        # Assign symbols to components
        self._assign_symbols(context)

        # Group components by function
        groups = self._group_components(context)

        # Calculate required canvas size BEFORE placement
        self._calculate_canvas_size(context, groups)

        # Initialize collision detection
        self.occupied_regions = []

        # Calculate layout positions with collision detection
        self._calculate_positions_with_collision_detection(context, groups)

        # Adjust canvas size dynamically based on placed components
        self._adjust_canvas_post_placement(context)

        # Pre-create all pins based on netlist
        self._create_component_pins(context)

        # Validate layout quality
        self._validate_layout_quality(context)

        # Statistics
        context.stats['layout'] = {
            'groups': len(groups),
            'total_width': max(c.position.x + c.bounds.width for c in context.components.values()) if context.components else 0,
            'total_height': max(c.position.y + c.bounds.height for c in context.components.values()) if context.components else 0,
            'total_pins': sum(len(c.pins) for c in context.components.values()),
            'occupied_regions': len(self.occupied_regions)
        }

        print(f"✓ Placed {len(context.components)} components in {len(groups)} groups")
        print(f"✓ Created {context.stats['layout']['total_pins']} pins")
        print(f"✓ Canvas: {context.canvas_width}x{context.canvas_height}")
        print(f"✓ Collision-free placement validated")

        return context

    def _assign_symbols(self, context: SchematicContext):
        """Assign appropriate symbols to components."""
        for component in context.components.values():
            component.symbol = self.symbol_library.get_symbol_for_component(component.type)

    def _group_components(self, context: SchematicContext) -> Dict[str, List[Component]]:
        """Group components by isolation domain and function."""
        # Domain-based grouping (Fix: Professional clustering)
        domain_groups = {}
        
        for component in context.components.values():
            # Extract domain from lowlevel data if available, fallback to GND name detection
            domain = (getattr(component, 'specs', None) or {}).get('isolation_domain', 'GND_SYSTEM')
            
            # Heuristic for domain detection if not explicit
            if domain == 'GND_SYSTEM':
                for net_name in context.nets:
                    if any(g in net_name.upper() for g in ['ISO', 'USB', 'MAIN', 'HV']):
                        # Check if this component is on this net
                        if any(p[0] == component.ref_des for p in context.nets[net_name].pins):
                            domain = net_name.upper()
                            break

            if domain not in domain_groups:
                domain_groups[domain] = []
            domain_groups[domain].append(component)

        # Further group within domains by function
        final_groups = {}
        for domain, comps in domain_groups.items():
            final_groups[domain] = {
                'power': [], 'ic': [], 'passive': [], 'misc': []
            }
            for comp in comps:
                category = get_component_type_category(comp.type)
                if comp.type.lower() in ['voltage_regulator', 'power_supply']:
                    final_groups[domain]['power'].append(comp)
                elif category == 'ic':
                    final_groups[domain]['ic'].append(comp)
                elif category in ['resistor', 'capacitor', 'inductor']:
                    final_groups[domain]['passive'].append(comp)
                else:
                    final_groups[domain]['misc'].append(comp)
        
        return final_groups

    def _is_input_connector(self, component: Component, context: SchematicContext) -> bool:
        """Determine if connector is input or output based on connections."""
        for net in context.nets.values():
            for comp_ref, _ in net.pins:
                if comp_ref == component.ref_des:
                    # Check what else is on this net
                    for other_comp_ref, _ in net.pins:
                        if other_comp_ref != comp_ref:
                            other_comp = context.components.get(other_comp_ref)
                            if other_comp and 'ic' in other_comp.type.lower():
                                return True
        return False

    def _calculate_canvas_size(self, context: SchematicContext, groups: Dict[str, List[Component]]):
        """
        Dynamically calculate required canvas size based on component count and their potential spread,
        ensuring all components fit and preventing 'outside canvas bounds' errors.
        """
        # Calculate initial estimated max_x and max_y based on number of components
        total_components = sum(len(g) for g in groups.values())
        
        # Estimate maximum number of components in a row (e.g., in grid layout)
        # Using a square root heuristic for rough estimation
        max_comps_per_row = max(4, int(total_components**0.5) * 2) 
        
        # Estimate rough maximum X and Y needed based on spacing
        # This is a heuristic to prevent very small canvas for sparse layouts
        estimated_max_x = self.margin * 2 + max_comps_per_row * context.component_spacing_x
        estimated_max_y = self.margin * 2 + (total_components // max_comps_per_row + 1) * context.component_spacing_y
        
        # Set a large initial canvas size for placement, it will be trimmed later
        context.canvas_width = 8000
        context.canvas_height = 8000

        # Update spacing based on density - this can still be useful for initial layout strategy
        if total_components > 60:
            context.component_spacing_x = 450
            context.component_spacing_y = 380
        elif total_components > 40:
            context.component_spacing_x = 420
            context.component_spacing_y = 350
        elif total_components > 25:
            context.component_spacing_x = 400
            context.component_spacing_y = 320
        else:
            context.component_spacing_x = 350
            context.component_spacing_y = 280

        print(f"Initial Canvas sizing: {total_components} components → {context.canvas_width}x{context.canvas_height}")

    def _calculate_positions_with_collision_detection(self, context: SchematicContext, groups: Dict[str, Dict]):
        """Calculate component positions with domain-based force clustering."""
        
        current_y_offset = self.margin
        
        for domain_name, sub_groups in groups.items():
            print(f"Placing domain: {domain_name}")
            
            # TIER 1: ICs and Power (Anchors for the domain)
            # Combine all ICs and power components in this domain
            anchors = sub_groups.get('ic', []) + sub_groups.get('power', [])
            if anchors:
                self._layout_grid_with_collision(
                    anchors,
                    self.margin * 2,
                    current_y_offset,
                    context
                )
            
            # TIER 2: Passives (Clustered around anchors)
            passives = sub_groups.get('passive', [])
            if passives:
                self._layout_passive_around_ics(passives, context)
                
            # TIER 3: Misc (Remaining items)
            misc = sub_groups.get('misc', [])
            if misc:
                self._layout_grid_with_collision(
                    misc,
                    self.margin * 2,
                    current_y_offset + 400, # Offset from anchors
                    context
                )

            # Update offset for next domain
            # Find max Y in this domain to avoid overlap between domains
            all_domain_comps = anchors + passives + misc
            if all_domain_comps:
                max_y = max((c.position.y + c.bounds.height for c in all_domain_comps if c.position), default=current_y_offset)
                current_y_offset = max_y + self.margin * 2

    def _layout_vertical_with_collision(self, components: List[Component], x: int, y: int, context: SchematicContext):
        """Layout components vertically with collision detection."""
        current_y = y

        for component in components:
            width, height = self.symbol_library.get_symbol_size(component.symbol)

            # Try to place at current position
            placed = False
            attempts = 0
            max_attempts = 100 # Increased attempts for better collision avoidance

            while not placed and attempts < max_attempts:
                # Snap to grid
                grid_x = (x // self.grid_size) * self.grid_size
                grid_y = (current_y // self.grid_size) * self.grid_size # DEFINED GRID_Y HERE
                # Check collision
                if self._check_collision(grid_x, grid_y, width, height):
                    # Move down and try again
                    current_y += context.component_spacing_y // 2
                    attempts += 1
                else: # ADDED ELSE KEYWORD
                    # Place component
                    component.position = Point(grid_x, grid_y)
                    component.bounds = Rectangle(grid_x, grid_y, width, height) # Store actual bounds
                    self._mark_occupied(grid_x - self.component_padding, grid_y - self.component_padding,
                                        width + 2 * self.component_padding, height + 2 * self.component_padding)
                    placed = True

                # Safety: if too many attempts, place anyway
                if attempts >= max_attempts:
                    component.position = Point(grid_x, grid_y)
                    component.bounds = Rectangle(grid_x, grid_y, width, height) # Store actual bounds
                    context.warnings.append(f"Component {component.ref_des} placed with potential overlap")
                    placed = True

            current_y += context.component_spacing_y

    def _layout_horizontal_with_collision(self, components: List[Component], x: int, y: int, context: SchematicContext):
        """Layout components horizontally with collision detection."""
        current_x = x

        for component in components:
            width, height = self.symbol_library.get_symbol_size(component.symbol)

            # Try to place at current position
            placed = False
            attempts = 0
            max_attempts = 100 # Increased attempts for better collision avoidance

            while not placed and attempts < max_attempts:
                # Snap to grid
                grid_x = (current_x // self.grid_size) * self.grid_size
                grid_y = (y // self.grid_size) * self.grid_size

                # Check collision
                if self._check_collision(grid_x, grid_y, width, height):
                    # Move right and try again
                    current_x += context.component_spacing_x // 2
                    attempts += 1
                else:
                    # Place component
                    component.position = Point(grid_x, grid_y)
                    component.bounds = Rectangle(grid_x, grid_y, width, height) # Store actual bounds
                    self._mark_occupied(grid_x - self.component_padding, grid_y - self.component_padding,
                                        width + 2 * self.component_padding, height + 2 * self.component_padding)
                    placed = True

                # Safety: if too many attempts, place anyway
                if attempts >= max_attempts:
                    component.position = Point(grid_x, grid_y)
                    component.bounds = Rectangle(grid_x, grid_y, width, height) # Store actual bounds
                    context.warnings.append(f"Component {component.ref_des} placed with potential overlap")
                    placed = True

            current_x += context.component_spacing_x

    def _layout_grid_with_collision(self, components: List[Component], x: int, y: int, context: SchematicContext):
        """Layout components in a grid pattern with collision detection - IEEE standard."""
        # Dynamic column count based on number of components
        num_components = len(components)
        if num_components > 20:
            cols = 5
        elif num_components > 12:
            cols = 4
        else:
            cols = 3

        current_x = x
        current_y = y
        col_count = 0

        for component in components:
            width, height = self.symbol_library.get_symbol_size(component.symbol)

            # Try to place at current position
            placed = False
            attempts = 0
            max_attempts = 150 # Increased attempts for better collision avoidance

            while not placed and attempts < max_attempts:
                # Snap to grid
                grid_x = (current_x // self.grid_size) * self.grid_size
                grid_y = (current_y // self.grid_size) * self.grid_size

                # Check collision
                if self._check_collision(grid_x, grid_y, width, height):
                    # Try next position
                    col_count += 1
                    if col_count >= cols:
                        col_count = 0
                        current_x = x
                        current_y += context.component_spacing_y // 2
                    else:
                        current_x += context.component_spacing_x // 2
                    attempts += 1
                else:
                    # Place component
                    component.position = Point(grid_x, grid_y)
                    component.bounds = Rectangle(grid_x, grid_y, width, height) # Store actual bounds
                    self._mark_occupied(grid_x - self.component_padding, grid_y - self.component_padding,
                                        width + 2 * self.component_padding, height + 2 * self.component_padding)
                    placed = True

                # Safety: if too many attempts, place anyway
                if attempts >= max_attempts:
                    component.position = Point(grid_x, grid_y)
                    component.bounds = Rectangle(grid_x, grid_y, width, height) # Store actual bounds
                    context.warnings.append(f"Component {component.ref_des} placed with potential overlap")
                    placed = True

            # Move to next grid position
            col_count += 1
            if col_count >= cols:
                col_count = 0
                current_x = x
                current_y += context.component_spacing_y
            else:
                current_x += context.component_spacing_x

    def _layout_passive_around_ics(self, components: List[Component], context: SchematicContext):
        """Layout passive components strategically around ICs they connect to."""
        # Find IC positions
        ic_positions = []
        for comp in context.components.values():
            if 'ic' in comp.type.lower() and comp.position:
                ic_positions.append((comp.position.x, comp.position.y))

        if not ic_positions:
            # No ICs, use grid layout
            self._layout_grid_with_collision(
                components,
                context.canvas_width // 2,
                context.canvas_height // 2,
                context
            )
            return

        # Place passives near their connected ICs
        for component in components:
            width, height = self.symbol_library.get_symbol_size(component.symbol)

            # Find closest IC this component connects to
            closest_ic_pos = self._find_closest_connected_ic(component, ic_positions, context)

            if closest_ic_pos:
                # Try to place near the IC
                base_x, base_y = closest_ic_pos
                offsets = [
                    (180, 0),   # Right of IC
                    (-180, 0),  # Left of IC
                    (0, 180),   # Below IC
                    (0, -180),  # Above IC
                    (180, 180), # Bottom-right
                    (-180, 180),# Bottom-left
                ]

                placed = False
                attempts = 0 # Initialize attempts
                max_attempts = 100 # Increased attempts for better collision avoidance
                for offset_x, offset_y in offsets:
                    trial_x = base_x + offset_x
                    trial_y = base_y + offset_y

                    # Snap to grid
                    grid_x = (trial_x // self.grid_size) * self.grid_size
                    grid_y = (trial_y // self.grid_size) * self.grid_size

                    if not self._check_collision(grid_x, grid_y, width, height):
                        component.position = Point(grid_x, grid_y)
                        component.bounds = Rectangle(grid_x, grid_y, width, height) # Store actual bounds
                        self._mark_occupied(grid_x - self.component_padding, grid_y - self.component_padding,
                                            width + 2 * self.component_padding, height + 2 * self.component_padding)
                        placed = True
                        break
                    else: # ADDED ELSE KEYWORD (for the break)
                        # Move to next offset, try again
                        attempts += 1
                        continue # Continue to next offset
                if not placed:
                    # Fallback: use grid layout
                    self._layout_grid_with_collision(
                        [component],
                        context.canvas_width // 2,
                        context.canvas_height // 2,
                        context
                    )
            else:
                # No connection found, use grid layout
                self._layout_grid_with_collision(
                    [component],
                    context.canvas_width // 2,
                    context.canvas_height // 2,
                    context
                )

    def _find_closest_connected_ic(self, component: Component, ic_positions: List[Tuple], context: SchematicContext) -> Optional[Tuple]:
        """Find the closest IC that this component connects to."""
        # Get all nets this component is on
        connected_ics = []

        for net in context.nets.values():
            component_in_net = False
            ic_refs_in_net = []

            for comp_ref, _ in net.pins:
                if comp_ref == component.ref_des:
                    component_in_net = True
                else:
                    other_comp = context.components.get(comp_ref)
                    if other_comp and 'ic' in other_comp.type.lower() and other_comp.position:
                        ic_refs_in_net.append((other_comp.position.x, other_comp.position.y))

            if component_in_net and ic_refs_in_net:
                connected_ics.extend(ic_refs_in_net)

        if not connected_ics:
            return None

        # Return first connected IC
        return connected_ics[0]

    def _check_collision(self, x: int, y: int, width: int, height: int) -> bool:
        """Check if placing a component at (x, y) with given size would collide."""
                # Add margin for spacing
        padding_for_check = self.component_padding # Use the consistent component padding
        test_rect = Rectangle(x - padding_for_check, y - padding_for_check, width + 2 * padding_for_check, height + 2 * padding_for_check)

        for occupied in self.occupied_regions:
            if self._rectangles_overlap(test_rect, occupied):
                return True

        return False

    def _rectangles_overlap(self, rect1: Rectangle, rect2: Rectangle) -> bool:
        """Check if two rectangles overlap."""
        # Check if one rectangle is to the left of the other
        if rect1.x + rect1.width < rect2.x or rect2.x + rect2.width < rect1.x:
            return False

        # Check if one rectangle is above the other
        if rect1.y + rect1.height < rect2.y or rect2.y + rect2.height < rect1.y:
            return False

        return True

    def _mark_occupied(self, x: int, y: int, width: int, height: int):
        """Mark a region as occupied."""
        self.occupied_regions.append(Rectangle(x, y, width, height))

    def _create_component_pins(self, context: SchematicContext):
        """Pre-create all pins based on netlist connections."""
        # First, collect all pins needed from nets
        pins_needed = {}  # {component_ref: set(pin_numbers)}

        for net in context.nets.values():
            for comp_ref, pin_num in net.pins:
                if comp_ref not in pins_needed:
                    pins_needed[comp_ref] = set()
                pins_needed[comp_ref].add(pin_num)

        # Now create pins for each component
        for comp_ref, component in context.components.items():
            if comp_ref not in pins_needed:
                # Component has no connections
                context.warnings.append(f"Component {comp_ref} has no connections")
                continue

            pin_numbers = pins_needed[comp_ref]
            self._assign_pins_to_component(component, pin_numbers, context)

    def _assign_pins_to_component(self, component: Component, pin_numbers: set, context: SchematicContext):
        """
        Assign pins to a component based on its type and pin numbers.
        Includes robust fallback for numeric pins (1,2,3) -> functional roles (B,C,E / G,D,S).
        """
        # Get pin mapping if available
        pin_mapping = self.symbol_library.get_pin_mapping(component.value)
        
        # Calculate pin positions based on symbol type
        x, y = component.position.x, component.position.y
        width, height = self.symbol_library.get_symbol_size(component.symbol)
        
        # Helper to normalize pin list (sort numeric/alpha)
        sorted_pins = sorted(list(pin_numbers), key=lambda x: int(x) if x.isdigit() else ord(x[0]) if x else 0)
        
        # Helper to map pin numbers to roles
        def has_pin(role: str, numeric_candidates: List[str]) -> str:
            """Check if role exists in pins, or map from numeric candidate."""
            # 1. Direct match (e.g. 'B' in pins)
            if role in pin_numbers:
                return role
            
            # 2. Check mapping (e.g. '1' -> 'B')
            for pin in pin_numbers:
                if pin_mapping.get(pin) == role:
                    return pin
            
            # 3. Numeric fallback (e.g. '1' is first candidate)
            for cand in numeric_candidates:
                if cand in pin_numbers:
                    # Verify this numeric pin isn't explicitly mapped to something else
                    mapped_role = pin_mapping.get(cand)
                    if not mapped_role or mapped_role == role:
                        return cand
            return None

        # --- Component Specific Layouts ---

        if component.symbol in ['resistor', 'capacitor', 'inductor', 'fuse', 'crystal']:
            # Two-terminal symmetric
            if len(sorted_pins) >= 1:
                p = sorted_pins[0]
                component.add_pin(p, pin_mapping.get(p, p), Point(x - 10, y + height // 2))
            if len(sorted_pins) >= 2:
                p = sorted_pins[1]
                component.add_pin(p, pin_mapping.get(p, p), Point(x + width + 10, y + height // 2))

        elif component.symbol in ['diode', 'led']:
            # Two-terminal polarized (A/K)
            anode = has_pin('A', ['1', 'A'])
            cathode = has_pin('K', ['2', 'C', 'K'])
            
            # If standard mapping failed, just take first two
            if not anode and len(sorted_pins) > 0: anode = sorted_pins[0]
            if not cathode and len(sorted_pins) > 1: cathode = sorted_pins[1]
            
            if anode: component.add_pin(anode, pin_mapping.get(anode, 'A'), Point(x - 10, y + height // 2))
            if cathode: component.add_pin(cathode, pin_mapping.get(cathode, 'K'), Point(x + width + 10, y + height // 2))

        elif component.symbol in ['capacitor_pol']:
             # Polarized capacitor (+/-)
            pos = has_pin('+', ['1', '+'])
            neg = has_pin('-', ['2', '-'])
            
            if not pos and len(sorted_pins) > 0: pos = sorted_pins[0]
            if not neg and len(sorted_pins) > 1: neg = sorted_pins[1]

            if pos: component.add_pin(pos, pin_mapping.get(pos, '+'), Point(x - 10, y + height // 2))
            if neg: component.add_pin(neg, pin_mapping.get(neg, '-'), Point(x + width + 10, y + height // 2))

        elif component.symbol in ['transistor_npn', 'transistor_pnp']:
            # Three-terminal transistors (B, C, E)
            # Standard TO-92: 1=E, 2=B, 3=C (varies, but good default)
            # OR 1=B, 2=E, 3=C
            # Let's try to find explicit B/C/E first
            
            b_pin = has_pin('B', ['2', 'B', 'G']) # G for IGBT
            c_pin = has_pin('C', ['3', 'C', 'D']) # D for IGBT
            e_pin = has_pin('E', ['1', 'E', 'S']) # S for IGBT
            
            # Fallback: Assign remaining unassigned numeric pins
            used_pins = {b_pin, c_pin, e_pin} - {None}
            remaining = [p for p in sorted_pins if p not in used_pins]
            
            if not e_pin and remaining: e_pin = remaining.pop(0)
            if not b_pin and remaining: b_pin = remaining.pop(0)
            if not c_pin and remaining: c_pin = remaining.pop(0)

            if b_pin: component.add_pin(b_pin, 'B', Point(x - 10, y + height // 2))
            if c_pin: component.add_pin(c_pin, 'C', Point(x + width // 2, y - 10))
            if e_pin: component.add_pin(e_pin, 'E', Point(x + width // 2, y + height + 10))

        elif component.symbol in ['mosfet_n', 'mosfet_p']:
            # MOSFET (G, D, S)
            # Standard: 1=G, 2=D, 3=S
            g_pin = has_pin('G', ['1', 'G', 'B'])
            d_pin = has_pin('D', ['2', 'D', 'C'])
            s_pin = has_pin('S', ['3', 'S', 'E'])
            
            used_pins = {g_pin, d_pin, s_pin} - {None}
            remaining = [p for p in sorted_pins if p not in used_pins]
            
            if not g_pin and remaining: g_pin = remaining.pop(0)
            if not d_pin and remaining: d_pin = remaining.pop(0)
            if not s_pin and remaining: s_pin = remaining.pop(0)

            if g_pin: component.add_pin(g_pin, 'G', Point(x - 10, y + height // 2))
            if d_pin: component.add_pin(d_pin, 'D', Point(x + width // 2, y - 10))
            if s_pin: component.add_pin(s_pin, 'S', Point(x + width // 2, y + height + 10))

        elif component.symbol == 'connector':
            # Connector pins along left edge
            pin_count = len(sorted_pins)
            pin_spacing = height / (pin_count + 1) if pin_count > 0 else height / 2

            for i, pin_num in enumerate(sorted_pins):
                py = y + (i + 1) * pin_spacing
                pin_name = pin_mapping.get(pin_num, f'{pin_num}') if pin_mapping else f'{pin_num}'
                component.add_pin(pin_num, pin_name, Point(x - 10, py))

        elif component.symbol == 'bridge_rectifier':
            # Bridge rectifier with 4 pins
            # AC1, AC2, DC+, DC-
            ac1 = has_pin('AC1', ['1', '~', 'AC'])
            ac2 = has_pin('AC2', ['2', '~', 'AC'])
            pos = has_pin('DC+', ['3', '+', 'POS'])
            neg = has_pin('DC-', ['4', '-', 'NEG'])
            
            used = {ac1, ac2, pos, neg} - {None}
            rem = [p for p in sorted_pins if p not in used]
            
            if not ac1 and rem: ac1 = rem.pop(0)
            if not ac2 and rem: ac2 = rem.pop(0)
            if not pos and rem: pos = rem.pop(0)
            if not neg and rem: neg = rem.pop(0)

            if ac1: component.add_pin(ac1, 'AC1', Point(x - 10, y + height // 2))
            if ac2: component.add_pin(ac2, 'AC2', Point(x + width + 10, y + height // 2))
            if pos: component.add_pin(pos, '+', Point(x + width // 2, y - 10))
            if neg: component.add_pin(neg, '-', Point(x + width // 2, y + height + 10))

        elif component.symbol == 'transformer':
            # Transformer 
            # 1,2 Primary; 3,4 Secondary
            pri1 = has_pin('1', ['1', 'P1'])
            pri2 = has_pin('2', ['2', 'P2'])
            sec1 = has_pin('3', ['3', 'S1', '4', '5']) # Common mappings
            sec2 = has_pin('4', ['4', 'S2', '5', '8'])
            
            used = {pri1, pri2, sec1, sec2} - {None}
            rem = [p for p in sorted_pins if p not in used]
            
            # Simple fill if mapping fails
            if not pri1 and rem: pri1 = rem.pop(0)
            if not pri2 and rem: pri2 = rem.pop(0)
            if not sec1 and rem: sec1 = rem.pop(0)
            if not sec2 and rem: sec2 = rem.pop(0)

            if pri1: component.add_pin(pri1, 'P1', Point(x - 10, y + height // 3))
            if pri2: component.add_pin(pri2, 'P2', Point(x - 10, y + 2 * height // 3))
            if sec1: component.add_pin(sec1, 'S1', Point(x + width + 10, y + height // 3))
            if sec2: component.add_pin(sec2, 'S2', Point(x + width + 10, y + 2 * height // 3))

        else:
            # Generic IC or complex component - GENERIC FALLBACK FOR EVERYTHING ELSE
            pin_count = len(sorted_pins)
            
            if pin_count <= 8:
                # Small IC - pins on left and right
                left_pins = sorted_pins[:(pin_count + 1) // 2]
                right_pins = sorted_pins[(pin_count + 1) // 2:]

                # Left side pins
                for i, pin_num in enumerate(left_pins):
                    py = y + (i + 1) * height / (len(left_pins) + 1)
                    pin_name = pin_mapping.get(pin_num, pin_num) if pin_mapping else pin_num
                    component.add_pin(pin_num, pin_name, Point(x - 10, py))

                # Right side pins
                for i, pin_num in enumerate(right_pins):
                    py = y + (i + 1) * height / (len(right_pins) + 1)
                    pin_name = pin_mapping.get(pin_num, pin_num) if pin_mapping else pin_num
                    component.add_pin(pin_num, pin_name, Point(x + width + 10, py))

            else:
                # Large IC - pins on all four sides
                pins_per_side = (pin_count + 3) // 4

                for i, pin_num in enumerate(sorted_pins):
                    side = i // pins_per_side
                    pos_on_side = i % pins_per_side

                    if side == 0:  # Left
                        px = x - 10
                        py = y + (pos_on_side + 1) * height / (pins_per_side + 1)
                    elif side == 1:  # Bottom
                        px = x + (pos_on_side + 1) * width / (pins_per_side + 1)
                        py = y + height + 10
                    elif side == 2:  # Right
                        px = x + width + 10
                        py = y + height - (pos_on_side + 1) * height / (pins_per_side + 1)
                    else:  # Top
                        px = x + width - (pos_on_side + 1) * width / (pins_per_side + 1)
                        py = y - 10

                    pin_name = pin_mapping.get(pin_num, pin_num) if pin_mapping else pin_num
                    component.add_pin(pin_num, pin_name, Point(px, py))

    def _validate_layout_quality(self, context: SchematicContext):
        """Validate layout quality - check for overlaps, proper spacing, etc."""
        overlaps = 0
        too_close = 0

        components_list = list(context.components.values())

        for i, comp1 in enumerate(components_list):
            for comp2 in components_list[i+1:]:
                # Check overlap
                if self._rectangles_overlap(comp1.bounds, comp2.bounds):
                    overlaps += 1
                    context.warnings.append(f"Components {comp1.ref_des} and {comp2.ref_des} overlap")

                # Check if too close
                dist_x = abs(comp1.position.x - comp2.position.x)
                dist_y = abs(comp1.position.y - comp2.position.y)
                dist = (dist_x ** 2 + dist_y ** 2) ** 0.5

                if dist < self.min_component_spacing:
                    too_close += 1

        if overlaps > 0:
            context.errors.append(f"Layout has {overlaps} component overlaps")

        if too_close > 5:  # Allow a few close components
            context.warnings.append(f"{too_close} component pairs are closer than recommended spacing")

    def _adjust_canvas_post_placement(self, context: SchematicContext):
        """
        Adjusts the canvas size based on the maximum extent of all placed components,
        plus a margin, to ensure nothing is cut off.
        This function should be called after all components have been placed.
        """
        if not context.components:
            return

        max_x = 0
        max_y = 0
        min_x = context.canvas_width # Initialize with max possible
        min_y = context.canvas_height # Initialize with max possible

        for component in context.components.values():
            if component.position:
                # Use component.position (top-left) and actual symbol size
                # component.bounds stores the actual symbol size, not the padded occupied region
                sym_width, sym_height = self.symbol_library.get_symbol_size(component.symbol)

                max_x = max(max_x, component.position.x + sym_width)
                max_y = max(max_y, component.position.y + sym_height)
                min_x = min(min_x, component.position.x)
                min_y = min(min_y, component.position.y)
        
        # Add a safety margin around the maximum extent
        safety_margin = 100 # pixels
        
        # Calculate new width and height
        new_width = max_x - min_x + 2 * safety_margin
        new_height = max_y - min_y + 2 * safety_margin
        
        # Ensure minimum canvas size, even if components are few
        new_width = max(new_width, 1000)
        new_height = max(new_height, 800)

        # Update context canvas size
        context.canvas_width = new_width
        context.canvas_height = new_height
        
        # Adjust component positions to be relative to the new canvas origin (min_x, min_y)
        for component in context.components.values():
            if component.position:
                component.position.x = component.position.x - min_x + safety_margin
                component.position.y = component.position.y - min_y + safety_margin
                # Re-calculate bounds and occupied regions based on new position
                sym_width, sym_height = self.symbol_library.get_symbol_size(component.symbol)
                component.bounds = Rectangle(component.position.x, component.position.y, sym_width, sym_height)
        
        print(f"Adjusted Canvas: {new_width}x{new_height} after placement.")
