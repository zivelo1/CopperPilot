# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Digikey API Integration for BOM Generation
============================================

Uses OAuth2 authentication and ProductInformation V4 API.

TC #82 (2025-12-15): Fixed timeout handling
- Increased default timeout from 15s to 30s for better reliability
- Added separate connect_timeout (10s) and read_timeout (30s)
- Improved error handling and logging for timeout scenarios
- Made timeouts configurable via constructor parameters

IMPORTANT: This module gracefully falls back to mock data when the Digikey
API is unavailable or times out. This ensures the BOM generation process
continues even during network issues.
"""
import os
import json
import time
import asyncio
import requests
from typing import Dict, List, Optional
from pathlib import Path
from server.config import Config
from utils.logger import setup_logger

logger = setup_logger(__name__)


# =============================================================================
# DEFAULT TIMEOUT CONFIGURATION
# =============================================================================
# TC #82: Increased timeouts for better reliability with slow API responses
DEFAULT_CONNECT_TIMEOUT = 10  # Seconds to wait for connection establishment
DEFAULT_READ_TIMEOUT = 30     # Seconds to wait for response after connection
DEFAULT_AUTH_TIMEOUT = 15     # Seconds to wait for OAuth2 token


class DigikeyAPI:
    """
    Interface to Digikey's API for component search and pricing.

    This class handles:
    - OAuth2 authentication with token caching
    - ProductInformation V4 API for keyword search
    - Automatic retry with exponential backoff
    - Graceful fallback to mock data on failures

    TC #82: Added configurable timeouts for better control over API behavior.
    """

    def __init__(
        self,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        auth_timeout: float = DEFAULT_AUTH_TIMEOUT,
    ):
        """
        Initialize the Digikey API client.

        Args:
            connect_timeout: Seconds to wait for connection establishment (default 10s)
            read_timeout: Seconds to wait for response after connection (default 30s)
            auth_timeout: Seconds to wait for OAuth2 token acquisition (default 15s)
        """
        self.client_id = Config.DIGIKEY_CLIENT_ID
        self.client_secret = Config.DIGIKEY_CLIENT_SECRET
        self.base_url = "https://api.digikey.com"
        self.api_version = "v4"

        # TC #82: Configurable timeout values
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.auth_timeout = auth_timeout

        # OAuth2 token management
        self.access_token = None
        self.token_expiry = 0
        self.token_file = Path(".digikey_token.json")

        # Load cached token if available
        self._load_token()

        logger.info(
            f"Digikey API initialized (timeouts: connect={connect_timeout}s, "
            f"read={read_timeout}s, auth={auth_timeout}s)"
        )

    def _load_token(self):
        """Load cached OAuth2 token from file"""
        if self.token_file.exists():
            try:
                with open(self.token_file, 'r') as f:
                    token_data = json.load(f)
                    self.access_token = token_data.get('access_token')
                    self.token_expiry = token_data.get('expiry', 0)

                    # Check if token is still valid
                    if time.time() < self.token_expiry:
                        logger.info("Loaded cached Digikey token")
                    else:
                        logger.info("Cached Digikey token expired")
                        self.access_token = None
            except Exception as e:
                logger.warning(f"Failed to load cached token: {e}")

    def _save_token(self, token: str, expires_in: int):
        """Save OAuth2 token to file"""
        try:
            token_data = {
                'access_token': token,
                'expiry': time.time() + expires_in - 60  # 60 sec buffer
            }
            with open(self.token_file, 'w') as f:
                json.dump(token_data, f)
            logger.info("Saved Digikey token to cache")
        except Exception as e:
            logger.warning(f"Failed to save token: {e}")

    def _is_token_valid(self) -> bool:
        """
        Check if current token exists and hasn't expired.
        Returns True if token is valid and usable.
        """
        if not self.access_token:
            return False

        # Check expiry with 60 second buffer
        return time.time() < (self.token_expiry - 60)

    def _get_access_token(self) -> bool:
        """
        Obtain OAuth2 access token using Client Credentials flow
        Returns True if successful
        """
        # Check if we have a valid token
        if self._is_token_valid():
            return True

        if not self.client_id or not self.client_secret:
            logger.warning("Digikey API credentials not configured")
            return False

        logger.info("Requesting new Digikey OAuth2 token...")

        url = f"{self.base_url}/v1/oauth2/token"

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }

        try:
            # TC #82: Use configurable auth timeout instead of hardcoded value
            response = requests.post(
                url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.auth_timeout,
            )

            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get('access_token')
                expires_in = data.get('expires_in', 3600)
                self.token_expiry = time.time() + expires_in - 60  # 60 sec buffer

                # Save token for future use
                self._save_token(self.access_token, expires_in)

                logger.info(f"Digikey OAuth2 token obtained (expires in {expires_in}s)")
                return True
            else:
                logger.error(f"Digikey OAuth2 error: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error obtaining Digikey token: {e}")
            return False

    def test_connection(self) -> bool:
        """
        Test API connectivity and authentication.
        Returns True if the API is reachable and a valid token can be obtained.
        """
        if not self.client_id or not self.client_secret:
            logger.warning("Digikey API: No credentials configured")
            return False

        success = self._get_access_token()
        if success:
            logger.info("Digikey API: Connection test passed (token acquired)")
        else:
            logger.error("Digikey API: Connection test failed (token acquisition failed)")
        return success

    async def _search_with_retry(self, keyword: str, limit: int = 10, max_retries: int = 3) -> List[Dict]:
        """
        Internal search method with exponential backoff retry logic

        Args:
            keyword: Search term
            limit: Maximum results
            max_retries: Maximum retry attempts

        Returns:
            List of part matches or empty list on failure
        """
        for attempt in range(max_retries):
            try:
                # Ensure we have a valid token before each attempt
                if not self._is_token_valid():
                    if not self._get_access_token():
                        logger.error(f"Digikey API: Token acquisition failed on attempt {attempt + 1}/{max_retries}")
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                            logger.info(f"Retrying in {wait_time} seconds...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error("Digikey API: All authentication attempts failed")
                            return []

                # FIXED: Corrected endpoint from research (Nov 2024)
                # OLD (WRONG): /Search/v4/Products/Keyword → 404 errors
                # NEW (CORRECT): /products/v4/search/keyword → Works!
                url = f"{self.base_url}/products/{self.api_version}/search/keyword"

                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "X-DIGIKEY-Client-Id": self.client_id,
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }

                payload = {
                    "Keywords": keyword,
                    "RecordCount": limit,
                    "RecordStartPosition": 0,
                    "Filters": {
                        "CategoryId": None,
                        "FamilyId": None,
                        "ManufacturerId": None,
                        "ParametricFilters": []
                    },
                    "Sort": {
                        "SortOption": "SortByUnitPrice",
                        "Direction": "Ascending"
                    },
                    "RequestedQuantity": 1
                }

                # TC #82: Use configurable timeouts with separate connect and read values
                # This provides better control over slow connections vs slow responses
                logger.debug(f"Digikey API: Attempt {attempt + 1}/{max_retries} for '{keyword}'")
                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=(self.connect_timeout, self.read_timeout),  # (connect, read) tuple
                )

                if response.status_code == 200:
                    data = response.json()
                    products = data.get("Products", [])
                    logger.info(f"Digikey API: Found {len(products)} results for '{keyword}'")
                    return [{
                        "part_number": product.get("ManufacturerPartNumber", ""),
                        "manufacturer": product.get("Manufacturer", {}).get("Name", ""),
                        "description": product.get("ProductDescription", ""),
                        "datasheet": product.get("DatasheetUrl", ""),
                        "stock": product.get("QuantityAvailable", 0),
                        "unit_price": self._extract_price(product.get("StandardPricing", [])),
                        "min_quantity": product.get("MinimumOrderQuantity", 1),
                        "image_url": product.get("PrimaryPhoto", ""),
                        "category": product.get("Category", {}).get("Name", ""),
                        "digikey_part_number": product.get("DigiKeyPartNumber", ""),
                        "packaging": product.get("Packaging", {}).get("Name", ""),
                        "series": product.get("Series", {}).get("Name", ""),
                        "supplier": "Digikey"
                    } for product in products]

                elif response.status_code == 401:
                    logger.warning(f"Digikey API: Auth failed on attempt {attempt + 1}, clearing token")
                    self.access_token = None
                    self.token_expiry = 0
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        await asyncio.sleep(wait_time)
                        continue

                else:
                    logger.error(f"Digikey API error {response.status_code}: {response.text}")
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        await asyncio.sleep(wait_time)
                        continue

                return []

            except requests.exceptions.ConnectTimeout:
                # TC #82: Distinguish between connection and read timeouts
                logger.warning(
                    f"Digikey API: Connection timeout ({self.connect_timeout}s) on attempt "
                    f"{attempt + 1}/{max_retries} for '{keyword}'"
                )
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Digikey API: Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                return []

            except requests.exceptions.ReadTimeout:
                # TC #82: Read timeout means connection succeeded but response was slow
                logger.warning(
                    f"Digikey API: Read timeout ({self.read_timeout}s) on attempt "
                    f"{attempt + 1}/{max_retries} for '{keyword}' - server is slow"
                )
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Digikey API: Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                return []

            except requests.exceptions.Timeout:
                # TC #82: Generic timeout fallback (shouldn't hit this with specific handlers)
                logger.warning(
                    f"Digikey API: Timeout on attempt {attempt + 1}/{max_retries} for '{keyword}'"
                )
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Digikey API: Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                return []

            except requests.exceptions.ConnectionError as e:
                # TC #82: Handle network connectivity issues
                logger.warning(
                    f"Digikey API: Connection error on attempt {attempt + 1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Digikey API: Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                return []

            except Exception as e:
                logger.error(f"Digikey API error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Digikey API: Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                return []

        # All retries exhausted
        logger.warning(
            f"Digikey API: All {max_retries} attempts failed for '{keyword}' - using mock data"
        )
        return []

    @staticmethod
    def _sanitize_keyword(keyword: str) -> str:
        """Fix IX.1: Sanitize Unicode characters using shared config map."""
        for char, replacement in Config.UNICODE_SANITIZE_MAP.items():
            keyword = keyword.replace(char, replacement)
        return keyword

    async def search_part(self, keyword: str, limit: int = 10) -> List[Dict]:
        """
        Search for parts by keyword using ProductInformation V4 API

        Args:
            keyword: Search term (e.g., "STM32F103", "10uF capacitor")
            limit: Maximum number of results

        Returns:
            List of part matches with details
        """
        keyword = self._sanitize_keyword(keyword)

        # Use retry logic for robustness
        results = await self._search_with_retry(keyword, limit)

        # Fallback to mock data if all retries failed
        if not results:
            logger.warning(f"Digikey API: Search failed for '{keyword}', using mock data")
            return self._get_mock_results(keyword)

        return results

    async def get_product_details(self, digikey_part_number: str) -> Optional[Dict]:
        """
        Get detailed information about a specific part

        Args:
            digikey_part_number: Digikey part number

        Returns:
            Detailed part information
        """
        if not self._get_access_token():
            return None

        url = f"{self.base_url}/Search/{self.api_version}/Products/{digikey_part_number}"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-DIGIKEY-Client-Id": self.client_id,
            "Accept": "application/json"
        }

        try:
            # TC #82: Use configurable timeouts for product details request
            logger.info(f"Digikey API: Getting details for '{digikey_part_number}'...")
            response = requests.get(
                url,
                headers=headers,
                timeout=(self.connect_timeout, self.read_timeout),
            )

            if response.status_code == 200:
                product = response.json()
                logger.info(f"Digikey API: Retrieved details for '{digikey_part_number}'")

                return {
                    "part_number": product.get("ManufacturerPartNumber", ""),
                    "manufacturer": product.get("Manufacturer", {}).get("Name", ""),
                    "description": product.get("ProductDescription", ""),
                    "datasheet": product.get("DatasheetUrl", ""),
                    "stock": product.get("QuantityAvailable", 0),
                    "price_breaks": product.get("StandardPricing", []),
                    "specifications": product.get("Parameters", []),
                    "lifecycle_status": product.get("ProductStatus", {}).get("Status", ""),
                    "rohs_status": product.get("RoHS", {}).get("RohsStatus", ""),
                    "lead_time": product.get("ManufacturerLeadWeeks", ""),
                    "packaging": product.get("Packaging", {}).get("Name", ""),
                    "image_url": product.get("PrimaryPhoto", ""),
                    "series": product.get("Series", {}).get("Name", ""),
                    "supplier": "Digikey"
                }

            return None

        except Exception as e:
            logger.error(f"Error getting Digikey product details: {e}")
            return None

    def _extract_price(self, price_breaks: List[Dict]) -> float:
        """Extract the unit price from price breaks"""
        if not price_breaks:
            return 0.0

        # Get the price for quantity 1 or the lowest quantity
        for pb in price_breaks:
            if pb.get("BreakQuantity") == 1:
                try:
                    return float(pb.get("UnitPrice", 0))
                except:
                    return 0.0

        # If no quantity 1, get the first price
        if price_breaks:
            try:
                return float(price_breaks[0].get("UnitPrice", 0))
            except:
                return 0.0

        return 0.0

    def _get_mock_results(self, keyword: str) -> List[Dict]:
        """Return mock results when API is not available"""
        logger.info(f"Digikey API: Using mock data for '{keyword}'")

        # Mock data for testing
        mock_parts = {
            "resistor": [
                {
                    "part_number": "RC0805FR-0710KL",
                    "manufacturer": "Yageo",
                    "description": "RES 10K OHM 1% 1/8W 0805",
                    "datasheet": "http://www.yageo.com/documents/recent/PYu-RC_Group_51_RoHS_L_11.pdf",
                    "stock": 75000,
                    "unit_price": 0.0018,
                    "min_quantity": 1,
                    "category": "Resistors",
                    "digikey_part_number": "311-10.0KCRCT-ND",
                    "packaging": "Cut Tape",
                    "supplier": "Digikey"
                }
            ],
            "capacitor": [
                {
                    "part_number": "GRM188R71C105KA12D",
                    "manufacturer": "Murata",
                    "description": "CAP CER 1UF 16V X7R 0603",
                    "datasheet": "",
                    "stock": 150000,
                    "unit_price": 0.045,
                    "min_quantity": 1,
                    "category": "Capacitors",
                    "digikey_part_number": "490-1606-1-ND",
                    "packaging": "Cut Tape",
                    "supplier": "Digikey"
                }
            ],
            "mosfet": [
                {
                    "part_number": "IRFZ44NPBF",
                    "manufacturer": "Infineon",
                    "description": "MOSFET N-CH 55V 49A TO-220AB",
                    "datasheet": "",
                    "stock": 8000,
                    "unit_price": 1.18,
                    "min_quantity": 1,
                    "category": "Discrete Semiconductor Products",
                    "digikey_part_number": "IRFZ44NPBF-ND",
                    "packaging": "Tube",
                    "supplier": "Digikey"
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
            "part_number": f"MOCK-DK-{keyword[:10]}",
            "manufacturer": "Generic",
            "description": f"Mock Digikey part for {keyword}",
            "datasheet": "",
            "stock": 2000,
            "unit_price": 0.48,
            "min_quantity": 1,
            "category": "Components",
            "digikey_part_number": f"MOCK-DK-{keyword[:10]}-ND",
            "packaging": "Cut Tape",
            "supplier": "Digikey"
        }]

    async def find_best_match(self, component_type: str, value: str, package: str = None) -> Optional[Dict]:
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
        results = await self.search_part(keyword, limit=5)

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
