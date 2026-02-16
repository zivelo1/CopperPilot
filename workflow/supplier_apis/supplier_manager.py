# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Supplier Manager - Orchestrates parallel searches across multiple suppliers
Handles async logging to ensure terminal output stays synchronized
"""
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .mouser_api import MouserAPI
from .digikey_api import DigikeyAPI
from utils.logger import setup_logger

logger = setup_logger(__name__)


class SupplierManager:
    """
    Manages parallel component searches across Mouser and Digikey
    Ensures proper logging synchronization for parallel operations
    """

    def __init__(self, websocket_manager=None, project_id=None):
        self.mouser = MouserAPI()
        self.digikey = DigikeyAPI()
        self.logger = logger
        self.websocket_manager = websocket_manager
        self.project_id = project_id

        # Track statistics
        self.stats = {
            'mouser_searches': 0,
            'digikey_searches': 0,
            'mouser_results': 0,
            'digikey_results': 0,
            'mouser_errors': 0,
            'digikey_errors': 0
        }

    async def search_component_parallel(
        self,
        component_type: str,
        value: str,
        package: str = None,
        limit: int = 5
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Search for component in BOTH Mouser and Digikey simultaneously

        Args:
            component_type: Type of component (e.g., "RESISTOR", "CAPACITOR")
            value: Component value (e.g., "10K", "1uF")
            package: Package type (e.g., "0805", "TO-220")
            limit: Max results per supplier

        Returns:
            Tuple of (mouser_results, digikey_results)
        """
        # Build search query
        search_terms = [component_type, value]
        if package:
            search_terms.append(package)
        keyword = " ".join(search_terms)

        # Log start of parallel search (synchronized)
        self.logger.info(f"Searching both suppliers for: {keyword}")

        # Run both searches in parallel
        try:
            mouser_task = self._search_mouser_with_logging(keyword, limit)
            digikey_task = self._search_digikey_with_logging(keyword, limit)

            # Wait for both to complete
            mouser_results, digikey_results = await asyncio.gather(
                mouser_task,
                digikey_task,
                return_exceptions=True
            )

            # Handle exceptions
            if isinstance(mouser_results, Exception):
                self.logger.error(f"Mouser search failed: {mouser_results}")
                self.stats['mouser_errors'] += 1
                mouser_results = []

            if isinstance(digikey_results, Exception):
                self.logger.error(f"Digikey search failed: {digikey_results}")
                self.stats['digikey_errors'] += 1
                digikey_results = []

            # Log results summary (synchronized)
            self.logger.info(
                f"Search complete for '{keyword}': "
                f"Mouser={len(mouser_results)}, Digikey={len(digikey_results)}"
            )

            return mouser_results, digikey_results

        except Exception as e:
            self.logger.error(f"Parallel search failed: {e}")
            return [], []

    async def _search_mouser_with_logging(self, keyword: str, limit: int) -> List[Dict]:
        """
        Search Mouser with synchronized logging
        """
        try:
            self.logger.debug(f"[Mouser] Starting search for: {keyword}")
            self.stats['mouser_searches'] += 1

            results = await self.mouser.search_part(keyword, limit)

            self.stats['mouser_results'] += len(results)
            self.logger.debug(f"[Mouser] Found {len(results)} results for: {keyword}")

            return results

        except Exception as e:
            self.logger.error(f"[Mouser] Search error: {e}")
            raise

    async def _search_digikey_with_logging(self, keyword: str, limit: int) -> List[Dict]:
        """
        Search Digikey with synchronized logging
        """
        try:
            self.logger.debug(f"[Digikey] Starting search for: {keyword}")
            self.stats['digikey_searches'] += 1

            results = await self.digikey.search_part(keyword, limit)

            self.stats['digikey_results'] += len(results)
            self.logger.debug(f"[Digikey] Found {len(results)} results for: {keyword}")

            return results

        except Exception as e:
            self.logger.error(f"[Digikey] Search error: {e}")
            raise

    async def select_best_parts_parallel(
        self,
        components: List[Dict]
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Select best parts for ALL components from BOTH suppliers in parallel

        Args:
            components: List of component specifications

        Returns:
            Tuple of (mouser_bom, digikey_bom)
        """
        total = len(components)
        self.logger.info(f"Starting parallel part selection for {total} unique components...")

        mouser_bom = []
        digikey_bom = []

        for idx, component in enumerate(components, 1):
            # Log progress (synchronized)
            self.logger.info(f"Selecting parts: {idx}/{total} ({idx*100//total}%)")

            # Send progress update to UI if websocket available
            if self.websocket_manager and self.project_id:
                try:
                    await self.websocket_manager.send_update(self.project_id, {
                        "type": "step_progress",
                        "step": 4,
                        "step_name": "BOM Generation",
                        "total_parts": total,
                        "completed_parts": idx - 1,
                        "current_part": f"{component.get('type', '')} {component.get('value', '')}",
                        "progress_percent": (idx - 1) * 100 // total
                    })
                except Exception as e:
                    self.logger.debug(f"Failed to send websocket update: {e}")

            # Search both suppliers in parallel
            mouser_results, digikey_results = await self.search_component_parallel(
                component_type=component.get('type', ''),
                value=component.get('value', ''),
                package=component.get('package', ''),
                limit=5
            )

            # Select best from Mouser
            mouser_part = self._select_best_from_results(mouser_results, component)
            if mouser_part:
                mouser_bom.append(self._create_bom_item(component, mouser_part, 'Mouser'))
            else:
                # No Mouser match, use generic
                mouser_bom.append(self._create_generic_bom_item(component, 'Mouser'))

            # Select best from Digikey
            digikey_part = self._select_best_from_results(digikey_results, component)
            if digikey_part:
                digikey_bom.append(self._create_bom_item(component, digikey_part, 'Digikey'))
            else:
                # No Digikey match, use generic
                digikey_bom.append(self._create_generic_bom_item(component, 'Digikey'))

        self.logger.info(
            f"Part selection complete: {total}/{total} (100%) - "
            f"Mouser={len(mouser_bom)}, Digikey={len(digikey_bom)}"
        )

        return mouser_bom, digikey_bom

    def _select_best_from_results(self, results: List[Dict], component: Dict) -> Optional[Dict]:
        """
        Select the best matching part from search results

        Scoring criteria:
        - In stock: +10 points
        - Price < $1: +5 points
        - Description matches component type: +3 points
        - Description matches value: +3 points
        - Description matches package: +2 points
        - Has datasheet: +1 point
        """
        if not results:
            return None

        best_match = None
        best_score = 0

        comp_type = component.get('type', '').lower()
        value = component.get('value', '').lower()
        package = component.get('package', '').lower()

        for part in results:
            score = 0

            # Check if in stock
            if part.get("stock", 0) > 0:
                score += 10

            # Check price
            unit_price = part.get("unit_price", 999)
            if unit_price < 1.0:
                score += 5
            elif unit_price < 10.0:
                score += 3

            # Check if description contains our search terms
            desc_lower = part.get("description", "").lower()
            if comp_type and comp_type in desc_lower:
                score += 3
            if value and value in desc_lower:
                score += 3
            if package and package in desc_lower:
                score += 2

            # Prefer parts with datasheets
            if part.get("datasheet"):
                score += 1

            if score > best_score:
                best_score = score
                best_match = part

        return best_match

    def _create_bom_item(self, component: Dict, part: Dict, supplier: str) -> Dict:
        """
        Create BOM item from component and selected part
        """
        return {
            **component,  # Keep all original component data
            'manufacturer': part.get('manufacturer', 'Generic'),
            'partNumber': part.get('part_number', component.get('value')),
            'unitPrice': part.get('unit_price', 0.0),
            'datasheet': part.get('datasheet', ''),
            'stock': part.get('stock', 0),
            'supplier': supplier,
            'supplierPartNumber': part.get(f'{supplier.lower()}_part_number', ''),
            'minQuantity': part.get('min_quantity', 1),
            'packaging': part.get('packaging', ''),
            'selected': True  # Mark as AI-selected part
        }

    def _create_generic_bom_item(self, component: Dict, supplier: str) -> Dict:
        """
        Create generic BOM item when no supplier match found
        """
        return {
            **component,  # Keep all original component data
            'manufacturer': 'Generic',
            'partNumber': component.get('value'),
            'unitPrice': 0.0,
            'datasheet': '',
            'stock': 0,
            'supplier': supplier,
            'supplierPartNumber': '',
            'minQuantity': 1,
            'packaging': '',
            'selected': False  # Mark as not found
        }

    def get_statistics(self) -> Dict:
        """
        Get search statistics

        Returns:
            Dict with search statistics
        """
        return {
            **self.stats,
            'mouser_success_rate': (
                (self.stats['mouser_searches'] - self.stats['mouser_errors'])
                / max(self.stats['mouser_searches'], 1)
            ) * 100,
            'digikey_success_rate': (
                (self.stats['digikey_searches'] - self.stats['digikey_errors'])
                / max(self.stats['digikey_searches'], 1)
            ) * 100
        }

    def reset_statistics(self):
        """Reset statistics counters"""
        self.stats = {
            'mouser_searches': 0,
            'digikey_searches': 0,
            'mouser_results': 0,
            'digikey_results': 0,
            'mouser_errors': 0,
            'digikey_errors': 0
        }

    def test_connections(self) -> Dict[str, bool]:
        """
        Test connectivity to all supplier APIs before starting bulk search.

        Returns:
            Dict mapping supplier name to connection status (True/False)
        """
        results = {
            'mouser': self.mouser.test_connection(),
            'digikey': self.digikey.test_connection(),
        }
        self.logger.info(f"Supplier connection test: {results}")
        return results

    def write_search_summary(self, output_dir: str) -> None:
        """
        Write a JSON summary of all search activity to the BOM output directory.
        Includes per-supplier statistics and success rates.

        Args:
            output_dir: Directory to write the summary file into
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        summary = {
            'statistics': self.get_statistics(),
            'raw_counts': self.stats,
        }

        summary_file = output_path / 'supplier_search_summary.json'
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        self.logger.info(f"Search summary written to {summary_file}")
