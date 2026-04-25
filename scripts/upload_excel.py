#!/usr/bin/env python3
"""
Manual upload CLI tool for Excel import.

Usage:
    python scripts/upload_excel.py <path_to_file.xlsx> <bitrix_domain>

Example:
    python scripts/upload_excel.py template_data/plan_fact_filled.xlsx build-control.bitrix24.ru
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure project root and scripts dir are in path when running as script
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from bitrix.client import BitrixClient
from config import settings
from import_excel import ExcelImporter


logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


def validate_inputs(file_path: str, domain: str) -> None:
    """Validate input parameters."""
    file_obj = Path(file_path)

    if not file_obj.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.lower().endswith((".xlsx", ".xls")):
        raise ValueError(f"File must be Excel format (.xlsx or .xls), got: {file_path}")

    if not domain:
        raise ValueError("Domain parameter required (e.g., build-control.bitrix24.ru)")

    logger.info(f"✓ File exists: {file_path}")
    logger.info(f"✓ Domain: {domain}")


async def run_import(file_path: str, domain: str) -> int:
    """
    Run the Excel import process.

    Returns:
        Exit code (0 = success, 1 = error)
    """
    try:
        validate_inputs(file_path, domain)
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"✗ Validation failed: {e}")
        return 1

    try:
        settings.validate()
    except ValueError as e:
        logger.error(f"✗ Configuration error: {e}")
        logger.error("Make sure .env file is configured with BITRIX24_WEBHOOK_URL and BITRIX24_DOMAIN")
        return 1

    logger.info("=" * 60)
    logger.info("Excel Import Tool - BuildControl MVP")
    logger.info("=" * 60)

    try:
        async with BitrixClient() as client:
            importer = ExcelImporter(client)
            result = await importer.import_file(file_path)

            logger.info("=" * 60)
            logger.info("✓ Import successful!")
            logger.info("=" * 60)
            print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
            return 0

    except Exception as e:
        logger.error(f"✗ Import failed: {e}")
        return 1


def main() -> int:
    """Main CLI entry point."""
    if len(sys.argv) < 3:
        print(__doc__)
        print("Error: Missing arguments")
        print(f"Usage: {sys.argv[0]} <file_path> <domain>")
        return 1

    file_path = sys.argv[1]
    domain = sys.argv[2]

    return asyncio.run(run_import(file_path, domain))


if __name__ == "__main__":
    sys.exit(main())
