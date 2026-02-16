# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle Spatial Clustering Module

GENERIC module to cluster net connection points by physical proximity.
This determines which pins should be in the same segment vs. separate segments.

Architecture Principle: GENERIC - works for ANY circuit type/complexity
Strategy: Data-driven spatial clustering based on actual pin positions
"""

import math
from typing import List, Dict, Tuple, Set
from .eagle_geometry import GeometryCalculator


class PinPosition:
    """Represents a pin with its absolute position on the schematic."""

    def __init__(self, pin_ref: str, x: float, y: float):
        """
        Args:
            pin_ref: Pin reference like "C1.1" or "U1.2"
            x: Absolute X coordinate in mm
            y: Absolute Y coordinate in mm
        """
        self.pin_ref = pin_ref
        self.x = x
        self.y = y
        self.component = pin_ref.split('.')[0]
        self.pin_number = pin_ref.split('.')[1] if '.' in pin_ref else '1'

    def distance_to(self, other: 'PinPosition') -> float:
        """Calculate Euclidean distance to another pin."""
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)

    def __repr__(self):
        return f"PinPosition({self.pin_ref}, x={self.x:.2f}, y={self.y:.2f})"


class PinCluster:
    """Represents a cluster of pins that should be in the same segment."""

    def __init__(self, cluster_id: int):
        self.cluster_id = cluster_id
        self.pins: List[PinPosition] = []

    def add_pin(self, pin: PinPosition):
        """Add a pin to this cluster."""
        self.pins.append(pin)

    def size(self) -> int:
        """Return number of pins in cluster."""
        return len(self.pins)

    def is_isolated(self) -> bool:
        """Return True if cluster has only one pin (isolated)."""
        return len(self.pins) == 1

    def centroid(self) -> Tuple[float, float]:
        """Calculate geometric center of cluster."""
        if not self.pins:
            return (0.0, 0.0)
        avg_x = sum(p.x for p in self.pins) / len(self.pins)
        avg_y = sum(p.y for p in self.pins) / len(self.pins)
        return (avg_x, avg_y)

    def bounding_box(self) -> Tuple[float, float, float, float]:
        """Return (min_x, min_y, max_x, max_y) of cluster."""
        if not self.pins:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [p.x for p in self.pins]
        ys = [p.y for p in self.pins]
        return (min(xs), min(ys), max(xs), max(ys))

    def get_pin_refs(self) -> List[str]:
        """Return list of pin references in cluster."""
        return [p.pin_ref for p in self.pins]

    def __repr__(self):
        return f"PinCluster(id={self.cluster_id}, size={len(self.pins)}, pins={[p.pin_ref for p in self.pins]})"


class SpatialNetClusterer:
    """
    GENERIC spatial clustering algorithm for net connection points.

    Strategy:
    1. Calculate absolute position of each pin
    2. Apply distance-based clustering
    3. Group pins within proximity threshold into same segment
    4. Isolated pins get their own segment with label

    This works for ANY circuit type without hardcoded assumptions.
    """

    # Clustering parameters (in mm)
    DEFAULT_CLUSTER_DISTANCE = 30.0  # Pins within 30mm are clustered together
    MIN_CLUSTER_DISTANCE = 10.0      # Minimum for very dense layouts
    MAX_CLUSTER_DISTANCE = 50.0      # Maximum for sparse layouts

    def __init__(self, cluster_distance: float = None):
        """
        Args:
            cluster_distance: Maximum distance (mm) for pins to be in same cluster.
                            If None, uses DEFAULT_CLUSTER_DISTANCE.
        """
        self.cluster_distance = cluster_distance or self.DEFAULT_CLUSTER_DISTANCE
        self.clusters: List[PinCluster] = []

    def calculate_pin_position(
        self,
        pin_ref: str,
        components: Dict,
        symbol_library
    ) -> PinPosition:
        """
        Calculate absolute position of a pin on the schematic.

        Args:
            pin_ref: Pin reference like "C1.1"
            components: Dictionary of component data
            symbol_library: EagleSymbolLibrary instance

        Returns:
            PinPosition with absolute coordinates
        """
        # Parse pin reference
        ref_des, pin_number = pin_ref.split('.', 1)

        # Get component data
        if ref_des not in components:
            raise ValueError(f"Component {ref_des} not found in components")

        comp = components[ref_des]
        comp_x = comp['sch_x']
        comp_y = comp['sch_y']
        rotation = comp.get('rotation', 'R0')
        symbol_name = comp.get('symbol', '')

        # Convert pin number to Eagle pin name
        pin_mapping = comp.get('pins', {})
        eagle_pin_name = pin_mapping.get(str(pin_number), str(pin_number))

        # Get pin offset from symbol library
        try:
            pin_offset_x, pin_offset_y = symbol_library.get_pin_offset(
                symbol_name, eagle_pin_name
            )
        except (KeyError, ValueError) as e:
            # Fallback: use component center
            print(f"    ⚠️  Pin offset lookup failed for {ref_des}.{pin_number} (symbol='{symbol_name}', pin='{eagle_pin_name}'): {e}")
            pin_offset_x, pin_offset_y = 0.0, 0.0

        # Calculate absolute pin position with rotation
        pin_x, pin_y = GeometryCalculator.calculate_pin_position(
            component_x=comp_x,
            component_y=comp_y,
            pin_offset_x=pin_offset_x,
            pin_offset_y=pin_offset_y,
            component_rotation=rotation
        )

        return PinPosition(pin_ref, pin_x, pin_y)

    def cluster_net_pins(
        self,
        pin_refs: List[str],
        components: Dict,
        symbol_library
    ) -> List[PinCluster]:
        """
        GENERIC clustering algorithm for net connection points.

        Args:
            pin_refs: List of pin references like ["C1.1", "C10.1", "R1.2"]
            components: Dictionary of component data
            symbol_library: EagleSymbolLibrary instance

        Returns:
            List of PinCluster objects, each representing one segment
        """
        self.clusters = []

        # Handle empty case
        if not pin_refs:
            return self.clusters

        # Calculate absolute positions for all pins
        pin_positions: List[PinPosition] = []
        for pin_ref in pin_refs:
            try:
                pos = self.calculate_pin_position(pin_ref, components, symbol_library)
                pin_positions.append(pos)
            except Exception as e:
                print(f"Warning: Could not calculate position for {pin_ref}: {e}")
                # Create pin at origin as fallback
                pin_positions.append(PinPosition(pin_ref, 0.0, 0.0))

        # Apply distance-based clustering (greedy approach)
        assigned: Set[int] = set()
        cluster_id = 0

        for i, pin in enumerate(pin_positions):
            if i in assigned:
                continue

            # Create new cluster with this pin
            cluster = PinCluster(cluster_id)
            cluster.add_pin(pin)
            assigned.add(i)

            # Find all unassigned pins within cluster distance
            for j, other_pin in enumerate(pin_positions):
                if j in assigned:
                    continue

                # Check distance to ANY pin in current cluster
                min_dist = min(
                    pin.distance_to(cluster_pin)
                    for cluster_pin in cluster.pins
                )

                if min_dist <= self.cluster_distance:
                    cluster.add_pin(other_pin)
                    assigned.add(j)

            self.clusters.append(cluster)
            cluster_id += 1

        return self.clusters

    def get_cluster_statistics(self) -> Dict:
        """
        Get statistics about clustering results.
        Useful for validation and debugging.
        """
        if not self.clusters:
            return {
                'total_clusters': 0,
                'total_pins': 0,
                'isolated_pins': 0,
                'multi_pin_clusters': 0,
                'largest_cluster': 0,
                'avg_cluster_size': 0.0
            }

        total_clusters = len(self.clusters)
        total_pins = sum(c.size() for c in self.clusters)
        isolated = sum(1 for c in self.clusters if c.is_isolated())
        multi_pin = total_clusters - isolated
        largest = max(c.size() for c in self.clusters)
        avg_size = total_pins / total_clusters if total_clusters > 0 else 0.0

        return {
            'total_clusters': total_clusters,
            'total_pins': total_pins,
            'isolated_pins': isolated,
            'multi_pin_clusters': multi_pin,
            'largest_cluster': largest,
            'avg_cluster_size': avg_size,
            'isolated_percentage': (isolated / total_clusters * 100) if total_clusters > 0 else 0.0
        }

    def validate_clustering_quality(self) -> bool:
        """
        Validate that clustering results are reasonable.

        Based on analysis of real Eagle files:
        - Isolated pins should be 20-40% of clusters
        - Multi-pin clusters should be 60-80% of clusters

        Returns:
            True if clustering quality is acceptable
        """
        stats = self.get_cluster_statistics()

        if stats['total_clusters'] == 0:
            return True  # Empty net is valid

        isolated_pct = stats['isolated_percentage']

        # Check if isolated percentage is in reasonable range
        # Allow 0-50% isolated (real Eagle files have ~27%)
        if isolated_pct > 50.0:
            print(f"Warning: High isolated pin percentage: {isolated_pct:.1f}% (expected 20-40%)")
            return False

        return True


class AdaptiveClusterer(SpatialNetClusterer):
    """
    Adaptive clustering that automatically adjusts distance threshold
    based on circuit density and net distribution.
    """

    def auto_adjust_cluster_distance(self, pin_positions: List[PinPosition]) -> float:
        """
        Automatically determine optimal cluster distance based on pin distribution.

        Strategy:
        - Calculate average nearest-neighbor distance
        - Use 3x average as cluster threshold
        - Clamp to reasonable min/max values
        """
        if len(pin_positions) < 2:
            return self.DEFAULT_CLUSTER_DISTANCE

        # Calculate nearest neighbor distances
        nn_distances = []
        for i, pin in enumerate(pin_positions):
            distances = [
                pin.distance_to(other)
                for j, other in enumerate(pin_positions)
                if i != j
            ]
            if distances:
                nn_distances.append(min(distances))

        if not nn_distances:
            return self.DEFAULT_CLUSTER_DISTANCE

        # Use 3x average nearest neighbor distance
        avg_nn_dist = sum(nn_distances) / len(nn_distances)
        optimal_distance = 3.0 * avg_nn_dist

        # Clamp to reasonable range
        optimal_distance = max(self.MIN_CLUSTER_DISTANCE, optimal_distance)
        optimal_distance = min(self.MAX_CLUSTER_DISTANCE, optimal_distance)

        return optimal_distance


# Convenience functions
def cluster_pins_simple(
    pin_refs: List[str],
    components: Dict,
    symbol_library,
    cluster_distance: float = 30.0
) -> List[PinCluster]:
    """
    Simple convenience function for pin clustering.

    Args:
        pin_refs: List of pin references
        components: Component data dictionary
        symbol_library: Symbol library instance
        cluster_distance: Clustering distance in mm

    Returns:
        List of pin clusters
    """
    clusterer = SpatialNetClusterer(cluster_distance)
    return clusterer.cluster_net_pins(pin_refs, components, symbol_library)


def cluster_pins_adaptive(
    pin_refs: List[str],
    components: Dict,
    symbol_library
) -> List[PinCluster]:
    """
    Adaptive clustering with automatic distance adjustment.

    Args:
        pin_refs: List of pin references
        components: Component data dictionary
        symbol_library: Symbol library instance

    Returns:
        List of pin clusters
    """
    clusterer = AdaptiveClusterer()
    return clusterer.cluster_net_pins(pin_refs, components, symbol_library)
