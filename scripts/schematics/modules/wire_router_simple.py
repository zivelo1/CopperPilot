# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Wire routing module - SIMPLE RELIABLE VERSION
Focus: Connect ALL pins in every net, no fancy optimization
"""
from typing import Dict, List, Tuple, Optional
from .utils import SchematicContext, Wire, Point, get_wire_color

class WireRouter:
    """Simple reliable wire routing - connect all pins."""

    def __init__(self, config: Dict = None):
        self.config = config or {}

    def execute(self, context: SchematicContext) -> SchematicContext:
        """Route all nets using simple point-to-point connections."""
        print("\n=== Stage 3: Wire Routing (Simple Reliable) ===")

        routed = 0
        total_wires = 0
        skipped_nets = 0

        for net_name, net in context.nets.items():
            if len(net.pins) < 2:
                continue

            net.color = get_wire_color(net_name)
            pin_positions = self._get_pin_positions(net, context)

            if len(pin_positions) < 2:
                skipped_nets += 1
                if skipped_nets <= 3:
                    print(f"⚠️  Net '{net_name}' has {len(net.pins)} pins but only {len(pin_positions)} positions found")
                continue

            # Simple strategy: connect all pins to first pin (star topology)
            hub = pin_positions[0]

            for pin_pos in pin_positions[1:]:
                # Create L-shaped connection (horizontal then vertical)
                if pin_pos.x != hub.x or pin_pos.y != hub.y:
                    # Horizontal segment
                    if pin_pos.x != hub.x:
                        context.wires.append(Wire(
                            start=pin_pos,
                            end=Point(hub.x, pin_pos.y),
                            net=net.name,
                            color=net.color,
                            width=2
                        ))
                        total_wires += 1

                    # Vertical segment
                    if pin_pos.y != hub.y:
                        context.wires.append(Wire(
                            start=Point(hub.x, pin_pos.y),
                            end=hub,
                            net=net.name,
                            color=net.color,
                            width=2
                        ))
                        total_wires += 1

            routed += 1

        context.stats['routing'] = {
            'total_nets': len(context.nets),
            'routed_nets': routed,
            'total_wires': total_wires
        }

        print(f"✓ Routed {routed} nets with {total_wires} wire segments")

        return context

    def _get_pin_positions(self, net, context: SchematicContext) -> List[Point]:
        """Get all pin positions for a net."""
        positions = []
        for comp_ref, pin_num in net.pins:
            component = context.components.get(comp_ref)
            if component:
                pin = component.get_pin(pin_num)
                if pin:
                    positions.append(pin.position)
        return positions
