# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Mouser API Integration for BOM Generation
"""
import os
import json
import requests
from typing import Dict, List, Optional
from server.config import Config
from utils.logger import setup_logger

logger = setup_logger(__name__)


class MouserAPI:
    """Interface to Mouser's API for component search and pricing"""

    def __init__(self):
        self.api_key = Config.MOUSER_API_KEY
        self.base_url = "https://api.mouser.com/api/v1"
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self.api_key:
            logger.info("Mouser API initialized with API key")
        else:
            logger.warning("Mouser API key not configured — will use mock data")

    def test_connection(self) -> bool:
        """
        Test API connectivity and authentication.
        Returns True if the API is reachable and the key is valid.
        """
        if not self.api_key:
            logger.warning("Mouser API: No API key configured")
            return False

        try:
            response = requests.post(
                f"{self.base_url}/search/keyword?apiKey={self.api_key}",
                json={"SearchByKeywordRequest": {
                    "keyword": "test", "records": 1, "startingRecord": 0,
                    "searchOptions": "1", "searchWithYourSignUpLanguage": "N"
                }},
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                logger.info("Mouser API: Connection test passed")
                return True
            else:
                logger.error(
                    f"Mouser API: Connection test failed with HTTP {response.status_code}"
                )
                return False
        except Exception as e:
            logger.error(f"Mouser API: Connection test failed: {e}")
            return False

    @staticmethod
    def _sanitize_keyword(keyword: str) -> str:
        """Fix IX.1: Replace Unicode characters that Mouser API rejects (HTTP 400).

        The replacement map lives in Config.UNICODE_SANITIZE_MAP (single source
        of truth) so the same table can be reused by other supplier APIs.
        """
        for char, replacement in Config.UNICODE_SANITIZE_MAP.items():
            keyword = keyword.replace(char, replacement)
        return keyword

    async def search_part(self, keyword: str, limit: int = 10) -> List[Dict]:
        """
        Search for parts by keyword

        Args:
            keyword: Search term (e.g., "STM32F103", "10uF capacitor")
            limit: Maximum number of results

        Returns:
            List of part matches with details
        """
        keyword = self._sanitize_keyword(keyword)

        if not self.api_key:
            logger.warning("Mouser API key not configured, using mock data")
            return self._get_mock_results(keyword)

        url = f"{self.base_url}/search/keyword"

        payload = {
            "SearchByKeywordRequest": {
                "keyword": keyword,
                "records": limit,
                "startingRecord": 0,
                "searchOptions": "1",  # Search all
                "searchWithYourSignUpLanguage": "N"
            }
        }

        try:
            response = requests.post(
                f"{url}?apiKey={self.api_key}",
                json=payload,
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                parts = data.get("SearchResults", {}).get("Parts", [])
                logger.info(f"Mouser API: Found {len(parts)} results for '{keyword}'")

                return [{
                    "part_number": part.get("ManufacturerPartNumber", ""),
                    "manufacturer": part.get("Manufacturer", ""),
                    "description": part.get("Description", ""),
                    "datasheet": part.get("DatasheetUrl", ""),
                    "stock": int(part.get("Availability", "0").replace(" In Stock", "").replace(",", "") or 0),
                    "unit_price": self._extract_price(part.get("PriceBreaks", [])),
                    "min_quantity": part.get("Min", 1),
                    "image_url": part.get("ImagePath", ""),
                    "category": part.get("Category", ""),
                    "mouser_part_number": part.get("MouserPartNumber", "")
                } for part in parts]
            else:
                logger.error(
                    f"Mouser API error: HTTP {response.status_code} "
                    f"for '{keyword}': {response.text[:200]}"
                )
                return []

        except requests.exceptions.Timeout:
            logger.warning(f"Mouser API: Timeout searching for '{keyword}'")
            return self._get_mock_results(keyword)
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Mouser API: Connection error for '{keyword}': {e}")
            return self._get_mock_results(keyword)
        except Exception as e:
            logger.error(f"Mouser API: Unexpected error for '{keyword}': {e}")
            return self._get_mock_results(keyword)

    def get_part_details(self, part_number: str) -> Optional[Dict]:
        """
        Get detailed information about a specific part

        Args:
            part_number: Mouser part number

        Returns:
            Detailed part information
        """
        if not self.api_key:
            return None

        url = f"{self.base_url}/search/partnumber"

        payload = {
            "SearchByPartNumberRequest": {
                "mouserPartNumber": part_number,
                "partSearchOptions": ""
            }
        }

        try:
            response = requests.post(
                f"{url}?apiKey={self.api_key}",
                json=payload,
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                parts = data.get("SearchResults", {}).get("Parts", [])

                if parts:
                    part = parts[0]
                    return {
                        "part_number": part.get("ManufacturerPartNumber", ""),
                        "manufacturer": part.get("Manufacturer", ""),
                        "description": part.get("Description", ""),
                        "datasheet": part.get("DatasheetUrl", ""),
                        "stock": int(part.get("Availability", "0").replace(" In Stock", "").replace(",", "") or 0),
                        "price_breaks": part.get("PriceBreaks", []),
                        "specifications": part.get("ProductAttributes", []),
                        "lifecycle_status": part.get("LifecycleStatus", ""),
                        "rohs_status": part.get("ROHSStatus", ""),
                        "lead_time": part.get("LeadTime", ""),
                        "packaging": part.get("Packaging", ""),
                        "image_url": part.get("ImagePath", "")
                    }

            return None

        except Exception as e:
            logger.error(f"Mouser API: Error getting details for '{part_number}': {e}")
            return None

    def _extract_price(self, price_breaks: List[Dict]) -> float:
        """Extract the unit price from price breaks"""
        if not price_breaks:
            return 0.0

        # Get the price for quantity 1 or the lowest quantity
        for pb in price_breaks:
            if pb.get("Quantity") == 1:
                price_str = pb.get("Price", "0").replace("$", "").replace(",", "")
                try:
                    return float(price_str)
                except:
                    return 0.0

        # If no quantity 1, get the first price
        if price_breaks:
            price_str = price_breaks[0].get("Price", "0").replace("$", "").replace(",", "")
            try:
                return float(price_str)
            except:
                return 0.0

        return 0.0

    def _get_mock_results(self, keyword: str) -> List[Dict]:
        """Return mock results when API is not available"""
        # Mock data for testing
        mock_parts = {
            "resistor": [
                {
                    "part_number": "RC0805FR-0710KL",
                    "manufacturer": "Yageo",
                    "description": "10K Ohm 1% 0805 Resistor",
                    "datasheet": "http://www.yageo.com/documents/recent/PYu-RC_Group_51_RoHS_L_11.pdf",
                    "stock": 50000,
                    "unit_price": 0.002,
                    "min_quantity": 1,
                    "category": "Resistors",
                    "mouser_part_number": "603-RC0805FR-0710KL"
                }
            ],
            "capacitor": [
                {
                    "part_number": "GRM188R71C105KA12D",
                    "manufacturer": "Murata",
                    "description": "1uF 16V X7R 0603 Capacitor",
                    "datasheet": "",
                    "stock": 100000,
                    "unit_price": 0.05,
                    "min_quantity": 1,
                    "category": "Capacitors",
                    "mouser_part_number": "81-GRM188R71C105KA2D"
                }
            ],
            "mosfet": [
                {
                    "part_number": "IRFZ44NPBF",
                    "manufacturer": "Infineon",
                    "description": "N-Channel MOSFET 55V 49A TO-220",
                    "datasheet": "",
                    "stock": 5000,
                    "unit_price": 1.25,
                    "min_quantity": 1,
                    "category": "Semiconductors",
                    "mouser_part_number": "942-IRFZ44NPBF"
                }
            ]
        }

        # Find matching category
        keyword_lower = keyword.lower()
        for category, parts in mock_parts.items():
            if category in keyword_lower:
                return parts

        # Return generic mock part
        return [{
            "part_number": f"MOCK-{keyword[:10]}",
            "manufacturer": "Generic",
            "description": f"Mock part for {keyword}",
            "datasheet": "",
            "stock": 1000,
            "unit_price": 0.50,
            "min_quantity": 1,
            "category": "Components",
            "mouser_part_number": f"MOCK-{keyword[:10]}"
        }]

    def find_best_match(self, component_type: str, value: str, package: str = None) -> Optional[Dict]:
        """
        Find the best matching part for a component

        Args:
            component_type: Type of component (e.g., "RESISTOR", "CAPACITOR")
            value: Component value (e.g., "10K", "1uF")
            package: Package type (e.g., "0805", "TO-220")

        Returns:
            Best matching part or None
        """
        # Build search query
        search_terms = [component_type, value]
        if package:
            search_terms.append(package)

        keyword = " ".join(search_terms)

        # Search for parts
        results = self.search_part(keyword, limit=5)

        if not results:
            return None

        # Score and rank results
        best_match = None
        best_score = 0

        for part in results:
            score = 0

            # Check if in stock
            if part["stock"] > 0:
                score += 10

            # Check price (prefer lower price)
            if part["unit_price"] < 1.0:
                score += 5

            # Check if description contains our search terms
            desc_lower = part["description"].lower()
            if component_type.lower() in desc_lower:
                score += 3
            if value.lower() in desc_lower:
                score += 3
            if package and package.lower() in desc_lower:
                score += 2

            # Prefer parts with datasheets
            if part.get("datasheet"):
                score += 1

            if score > best_score:
                best_score = score
                best_match = part

        return best_match