"""
Low-level HTTP wrapper for Bitrix24 REST API.
All Bitrix24 calls must go through this module.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from config import settings


logger = logging.getLogger(__name__)

# Bitrix24 REST API rate limit: 2 requests/second per webhook.
# These are GLOBAL so all BitrixClient instances (e.g. concurrent imports) share the limit.
_MIN_INTERVAL = 0.5  # seconds between calls
_RATE_LIMIT_RETRIES = 5
_RATE_LIMIT_BACKOFF = 2.0  # seconds to wait on QUERY_LIMIT_EXCEEDED
_global_last_call: float = 0.0
_global_rate_lock: asyncio.Lock = asyncio.Lock()


class BitrixClient:
    """
    Low-level HTTP client for Bitrix24 REST API.
    Handles authentication, request/response logging, and error checking.
    """

    def __init__(
        self, webhook_url: Optional[str] = None, timeout: float = 30.0
    ) -> None:
        """
        Initialize Bitrix24 client.

        Args:
            webhook_url: Bitrix24 webhook URL (defaults to env var)
            timeout: HTTP request timeout in seconds
        """
        self.webhook_url = webhook_url or settings.bitrix24_webhook_url
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Call a Bitrix24 REST API method.

        Args:
            method: API method name (e.g., 'crm.item.list')
            params: Method parameters

        Returns:
            API response dict

        Raises:
            ValueError: If API returns an error
        """
        params = params or {}
        url = f"{self.webhook_url}{method}"

        for attempt in range(_RATE_LIMIT_RETRIES):
            # Enforce global minimum interval — shared across all instances
            async with _global_rate_lock:
                global _global_last_call
                elapsed = time.monotonic() - _global_last_call
                if elapsed < _MIN_INTERVAL:
                    await asyncio.sleep(_MIN_INTERVAL - elapsed)
                _global_last_call = time.monotonic()

            _log_request(method, params)
            response = await self.client.post(url, json=params)

            try:
                result = response.json()
            except Exception:
                response.raise_for_status()
                raise ValueError(f"Bitrix24 non-JSON response: {response.text[:500]}")

            _log_response(method, result)

            if "error" in result:
                error_code = result.get("error", "")
                error_msg = result.get("error_description", error_code)
                if "QUERY_LIMIT_EXCEEDED" in error_code and attempt < _RATE_LIMIT_RETRIES - 1:
                    wait = _RATE_LIMIT_BACKOFF * (attempt + 1)
                    logger.warning(f"Rate limit hit on {method}, retrying in {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)
                    continue
                raise ValueError(f"Bitrix24 API error ({method}): {error_msg}")

            return result

        raise ValueError(f"Bitrix24 API error ({method}): rate limit exceeded after {_RATE_LIMIT_RETRIES} retries")

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self) -> "BitrixClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


def _log_request(method: str, params: Dict[str, Any]) -> None:
    """Log API request with timestamp."""
    timestamp = datetime.now().isoformat()
    logger.info(f"[{timestamp}] → {method} {json.dumps(params, ensure_ascii=False)}")


def _log_response(method: str, result: Dict[str, Any]) -> None:
    """Log API response with timestamp."""
    timestamp = datetime.now().isoformat()
    if "error" in result:
        logger.error(f"[{timestamp}] ✗ {method}: {result.get('error')}")
    else:
        logger.info(f"[{timestamp}] ✓ {method}")
