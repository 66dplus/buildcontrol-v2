"""
Tests for BitrixClient.
"""

import pytest

from bitrix.client import BitrixClient


@pytest.mark.asyncio
async def test_bitrix_client_init() -> None:
    """Test BitrixClient initialization."""
    webhook_url = "https://test.bitrix24.ru/rest/1/test-token/"
    client = BitrixClient(webhook_url=webhook_url)

    assert client.webhook_url == webhook_url
    assert client.timeout == 30.0

    await client.close()


@pytest.mark.asyncio
async def test_bitrix_client_context_manager() -> None:
    """Test BitrixClient as async context manager."""
    webhook_url = "https://test.bitrix24.ru/rest/1/test-token/"

    async with BitrixClient(webhook_url=webhook_url) as client:
        assert client.webhook_url == webhook_url
