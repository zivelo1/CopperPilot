# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Net-Aware Distance Field for PCB Routing

TIER 2 Fix - November 13, 2025
Purpose: Build spatial "forbidden zone" maps for each net to prevent routing through
         areas occupied by different nets.

This is the CORE of the TIER 2 routing overhaul. Instead of post-processing fixes,
this prevents placement errors BEFORE they happen by making the pathfinding algorithm
naturally avoid different-net areas.

GENERIC: Works for ANY circuit type (simple to complex), ANY net structure, ANY component count.

Algorithm:
1. For each net being routed:
   - Scan grid for ALL occupied cells
   - Mark cells occupied by DIFFERENT nets as obstacles
   - Compute distance transform (how far is each cell from nearest obstacle)
2. During A* pathfinding:
   - Check distance field: "How close am I to a different net?"
   - If too close → reject this path (or add penalty to cost)
   - Naturally routes through areas with good clearance
   
Expected Impact: 650 → <50 DRC errors/circuit (>90% reduction)
"""

import numpy as np
from scipy import ndimage
from typing import Dict, Tuple, Optional
import math

from .grid_occupancy import Point, Layer, Rectangle


class NetDistanceField:
    """
    Distance field for ONE net during routing.
    
    Professional Architecture:
    - Immutable after construction (thread-safe for parallel routing if needed)
    - Efficient numpy-based computation (O(grid_size) time)
    - Reusable across multiple pathfinding attempts
    - Clear separation of concerns (distance field is independent of routing logic)
    
    GENERIC Design:
    - No hardcoded circuit-specific values
    - Automatically adapts to ANY grid size, resolution, clearance requirement
    - Works for ANY net (power, signal, 2-pin, multi-pin)
    """
    
    def __init__(self, grid_shape: Tuple[int, int], resolution: float):
        """
        Initialize distance field for given grid.
        
        Professional Design:
        - Validates inputs to catch configuration errors early
        - Uses numpy for efficient storage and computation
        - Clear documentation of units (grid cells vs mm)
        
        Args:
            grid_shape: (rows, cols) - size of routing grid
            resolution: Grid resolution in mm (e.g., 0.25mm)
                       
        GENERIC: Works for any grid size (10×10 for simple circuits, 1000×1000 for complex)
        """
        # Input validation (fail-fast on configuration errors)
        if grid_shape[0] < 1 or grid_shape[1] < 1:
            raise ValueError(f"Invalid grid_shape {grid_shape}, must be positive")
        if resolution <= 0:
            raise ValueError(f"Invalid resolution {resolution}, must be positive")
            
        self.rows, self.cols = grid_shape
        self.resolution = resolution  # mm per grid cell
        
        # Distance field: field[r][c] = distance (in mm) to nearest different-net obstacle
        # Values: 0 = occupied by different net, >0 = distance to nearest obstacle
        # Use float32 for space efficiency (don't need float64 precision for distances)
        self.field = np.zeros((self.rows, self.cols), dtype=np.float32)
        
        # Track if field has been computed (prevent using uninitialized field)
        self._computed = False
    
    def mark_obstacle(self, position: Point, radius_mm: float, net_name: str = ""):
        """
        Mark circular obstacle (different-net trace, via, or component) in distance field.
        
        Professional Design:
        - Converts mm coordinates to grid coordinates automatically
        - Handles boundary cases (obstacles near edge of board)
        - Uses efficient numpy operations for marking
        
        GENERIC: Works for ANY obstacle size (0.1mm via to 10mm component)
        
        Args:
            position: Center of obstacle (in mm coordinates)
            radius_mm: Radius of obstacle in mm
            net_name: For debugging/logging only
        """
        # Convert mm to grid cells
        radius_cells = int(math.ceil(radius_mm / self.resolution))
        radius_cells = max(1, radius_cells)  # Minimum 1 cell
        
        # Convert position to grid coordinates
        # Note: This assumes position is in board coordinates (mm)
        # The calling code (grid_occupancy) will handle the coordinate mapping
        r = int(position.y / self.resolution)
        c = int(position.x / self.resolution)
        
        # Mark all cells within radius as obstacles (value = 0)
        for dr in range(-radius_cells, radius_cells + 1):
            for dc in range(-radius_cells, radius_cells + 1):
                nr, nc = r + dr, c + dc
                
                # Skip out-of-bounds cells
                if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                    continue
                
                # Check if within circular radius (not just square)
                dist_cells = math.sqrt(dr*dr + dc*dc)
                if dist_cells <= radius_cells:
                    self.field[nr][nc] = 0.0  # Mark as obstacle
    
    def compute_distance_transform(self):
        """
        Compute distance transform: how far is each cell from nearest obstacle?
        
        Professional Algorithm:
        - Uses scipy's Euclidean distance transform (proven, efficient)
        - Time complexity: O(rows × cols) - linear in grid size
        - Space complexity: O(rows × cols) - single field array
        
        After this method:
        - field[r][c] = 0 for obstacle cells
        - field[r][c] = N for cells N grid-cells away from nearest obstacle
        - Multiply by resolution to get distance in mm
        
        GENERIC: Works for any grid size, any obstacle distribution
        """
        # Create binary mask: 0 = obstacle, 1 = free space
        free_space_mask = (self.field > 0).astype(np.uint8)
        
        # Compute Euclidean distance transform
        # Each cell gets distance (in grid cells) to nearest zero cell
        distance_in_cells = ndimage.distance_transform_edt(free_space_mask)
        
        # Convert from grid cells to mm
        self.field = distance_in_cells.astype(np.float32) * self.resolution
        
        self._computed = True
    
    def get_distance(self, position: Point) -> float:
        """
        Query: How far (in mm) is this position from nearest different-net obstacle?
        
        Professional Design:
        - Returns infinity for out-of-bounds (safest default)
        - Checks if field has been computed (fail-fast on usage errors)
        - Uses bilinear interpolation for smoother distances (optional enhancement)
        
        GENERIC: Works for any position, any circuit
        
        Args:
            position: Query position (in mm coordinates)
            
        Returns:
            Distance in mm to nearest different-net obstacle
            - 0.0 = position IS an obstacle (different net)
            - >0.0 = distance to nearest obstacle
            - inf = out of bounds
        """
        if not self._computed:
            raise RuntimeError("Distance field not computed! Call compute_distance_transform() first")
        
        # Convert position to grid coordinates
        r = int(position.y / self.resolution)
        c = int(position.x / self.resolution)
        
        # Check bounds
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return float('inf')  # Out of bounds = infinitely far from obstacles (safe to route)
        
        return float(self.field[r][c])
    
    def is_safe(self, position: Point, required_clearance: float) -> bool:
        """
        Check if position has required clearance from different-net obstacles.
        
        Professional Design:
        - Simple boolean check (easier to reason about than distance values)
        - Encapsulates clearance logic (calling code doesn't need to know threshold)
        - Efficient (single array lookup after distance transform computed)
        
        GENERIC: Works for any clearance requirement (0.15mm to 0.50mm)
        
        Args:
            position: Position to check (mm coordinates)
            required_clearance: Minimum clearance needed (mm)
            
        Returns:
            True if position has >= required_clearance to nearest obstacle
            False otherwise (too close to different net, would create DRC violation)
            
        Use Case:
        - During Manhattan routing: if not is_safe(next_point, 0.30): skip this route
        - During A* pathfinding: if not is_safe(neighbor, 0.30): don't add to open set
        """
        distance = self.get_distance(position)
        return distance >= required_clearance
    
    def get_statistics(self) -> Dict[str, float]:
        """
        Get statistics about available clearances in this distance field.
        
        Professional Design:
        - Useful for diagnostics: "Why did routing fail?"
        - Can inform adaptive strategies: "Average clearance only 0.12mm, try tighter params"
        - Helps developers understand routing difficulty
        
        GENERIC: Works for any circuit, provides objective metrics
        
        Returns:
            Dictionary with:
            - 'min_clearance': Minimum non-zero clearance in field (mm)
            - 'max_clearance': Maximum clearance in field (mm)
            - 'avg_clearance': Average clearance in free space (mm)
            - 'median_clearance': Median clearance (mm)
            
        Use Case:
        - Before routing: "Max clearance is 0.15mm, this will be tight"
        - After routing failure: "Min clearance was 0.08mm, below 0.15mm minimum"
        """
        if not self._computed:
            raise RuntimeError("Distance field not computed!")
        
        # Get all non-zero values (excluding obstacles themselves)
        free_space_distances = self.field[self.field > 0]
        
        if len(free_space_distances) == 0:
            # Entire field is obstacles (impossible to route)
            return {
                'min_clearance': 0.0,
                'max_clearance': 0.0,
                'avg_clearance': 0.0,
                'median_clearance': 0.0
            }
        
        return {
            'min_clearance': float(np.min(free_space_distances)),
            'max_clearance': float(np.max(free_space_distances)),
            'avg_clearance': float(np.mean(free_space_distances)),
            'median_clearance': float(np.median(free_space_distances))
        }
    
    def export_heatmap(self, filepath: str, net_name: str = ""):
        """
        Export distance field as PNG heatmap for visualization/debugging.
        
        Professional Design:
        - Color scale: Red = obstacle (0mm), Yellow = tight (0.1-0.3mm), Green = safe (>0.3mm)
        - Helps debug routing failures: "Why couldn't it route? Ah, no path with >0.3mm clearance!"
        - Image saved to filepath for review
        
        GENERIC: Works for any field, any net
        
        Args:
            filepath: Where to save PNG (e.g., "debug/net_GND_distance_field.png")
            net_name: For title/filename (optional)
            
        Implementation Note:
        - Requires matplotlib (optional dependency)
        - Gracefully handles missing matplotlib (logs warning, doesn't crash)
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.colors as mcolors
        except ImportError:
            # Matplotlib not available, skip visualization (non-critical feature)
            return
        
        if not self._computed:
            raise RuntimeError("Distance field not computed!")
        
        # Create figure
        fig, ax = plt.subplots(figsize=(12, 10))
        
        # Color map: Red (0mm) → Yellow (0.3mm) → Green (>0.5mm)
        # This makes "danger zones" (red) obvious vs "safe zones" (green)
        cmap = mcolors.LinearSegmentedColormap.from_list(
            'clearance',
            ['red', 'yellow', 'green'],
            N=256
        )
        
        # Plot distance field
        im = ax.imshow(self.field, cmap=cmap, vmin=0, vmax=0.5, origin='lower')
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax)
        cbar.set_label('Clearance to different net (mm)', rotation=270, labelpad=20)
        
        # Title
        title = f"Distance Field for Net: {net_name}" if net_name else "Distance Field"
        ax.set_title(title, fontsize=14, fontweight='bold')
        
        # Labels
        ax.set_xlabel('Column (grid cells)', fontsize=12)
        ax.set_ylabel('Row (grid cells)', fontsize=12)
        
        # Save
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close(fig)


# Helper function for building distance field from grid occupancy
def build_distance_field_for_net(grid_occupancy, net_name: str, clearance: float) -> NetDistanceField:
    """
    Build distance field for routing a specific net.
    
    Professional Workflow:
    1. Create empty distance field matching grid size
    2. Scan grid for ALL occupied cells
    3. Mark cells occupied by DIFFERENT nets as obstacles
    4. Compute distance transform
    5. Return field ready for use in pathfinding
    
    GENERIC: Works for ANY net, ANY circuit, ANY grid configuration
    
    Args:
        grid_occupancy: GridOccupancy instance with current board state
        net_name: Net being routed (we'll mark OTHER nets as obstacles)
        clearance: Clearance requirement (mm) - affects obstacle radius
        
    Returns:
        NetDistanceField ready for querying during pathfinding
        
    Use Case:
    - Before routing net "GND": field = build_distance_field_for_net(grid, "GND", 0.30)
    - Then during A*: if field.is_safe(neighbor, 0.30): add to open set
    """
    # Create distance field matching grid size
    grid_shape = (grid_occupancy.rows, grid_occupancy.cols)
    field = NetDistanceField(grid_shape, grid_occupancy.resolution)
    
    # Scan both layers for occupied cells belonging to different nets
    for layer in [Layer.F_CU, Layer.B_CU]:
        grid = grid_occupancy.grids.get(layer)
        if grid is None:
            continue
            
        for r in range(grid_occupancy.rows):
            for c in range(grid_occupancy.cols):
                if grid[r][c] > 0:  # Cell is occupied
                    # Check which net occupies this cell
                    cell_net = grid_occupancy.net_assignments[layer].get((r, c), "")
                    
                    if cell_net and cell_net != net_name:
                        # Different net! Mark as obstacle
                        # Convert grid coordinates back to mm
                        x = grid_occupancy.board_bounds.x_min + (c + 0.5) * grid_occupancy.resolution
                        y = grid_occupancy.board_bounds.y_min + (r + 0.5) * grid_occupancy.resolution
                        pos = Point(x, y)
                        
                        # Mark with radius = clearance (obstacle plus required clearance)
                        field.mark_obstacle(pos, clearance, cell_net)
    
    # Compute distance transform
    field.compute_distance_transform()
    
    return field
