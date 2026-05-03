"""
Configuration loader for BuildControl MVP.
Loads environment variables from .env file.
"""

import os
from typing import Optional
from dotenv import load_dotenv


# Load .env file
load_dotenv()


class Settings:
    """Application settings from environment variables."""

    def __init__(self) -> None:
        self.bitrix24_webhook_url: str = os.getenv(
            "BITRIX24_WEBHOOK_URL", ""
        )
        self.bitrix24_domain: str = os.getenv("BITRIX24_DOMAIN", "")
        self.vps_url: str = os.getenv("VPS_URL", "")
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

        # Telegram notifications
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
        self.notifications_enabled: bool = (
            os.getenv("NOTIFICATIONS_ENABLED", "false").lower() == "true"
        )

        # Procurement approval workflow
        self.purchase_approver_user_id: int = int(
            os.getenv("PURCHASE_APPROVER_USER_ID", "1") or 1
        )
        self.approval_link_secret: str = os.getenv("APPROVAL_LINK_SECRET", "")
        self.telegram_webhook_secret: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
        self.telegram_approver_chat_id: str = (
            os.getenv("TELEGRAM_APPROVER_CHAT_ID", "")
            or os.getenv("TELEGRAM_CHAT_ID", "")
        )
        self.max_proposal_file_mb: int = int(
            os.getenv("MAX_PROPOSAL_FILE_MB", "10") or 10
        )

        # OpenRouter / AI agent
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")

        # Comma-separated Telegram chat IDs authorised to use the director AI agent
        _director_ids = os.getenv("TELEGRAM_DIRECTOR_CHAT_IDS", "")
        self.telegram_director_chat_ids: set[int] = {
            int(x.strip()) for x in _director_ids.split(",") if x.strip().isdigit()
        }

        # SQLite database path
        self.db_path: str = os.getenv("DB_PATH", "/opt/buildcontrol/buildcontrol.db")

        # Shared bearer token guarding /api/* and /upload. Single per-deployment
        # secret — same trust boundary as .env. Required in prod.
        self.api_token: str = os.getenv("BUILDCONTROL_API_TOKEN", "")

    @property
    def bitrix_iframe_origin(self) -> str:
        """Origin (scheme + host) of the Bitrix24 portal that embeds the widget.

        Derived from BITRIX24_DOMAIN. Used to scope CORS away from "*".
        """
        domain = (self.bitrix24_domain or "").strip()
        if not domain:
            return ""
        return f"https://{domain}"

    def validate(self) -> None:
        """Validate that all required settings are configured."""
        if not self.bitrix24_webhook_url:
            raise ValueError(
                "BITRIX24_WEBHOOK_URL not set in .env"
            )
        if not self.bitrix24_domain:
            raise ValueError("BITRIX24_DOMAIN not set in .env")
        if not self.api_token:
            raise ValueError(
                "BUILDCONTROL_API_TOKEN not set in .env — required to "
                "guard /api/* and /upload. Generate with `python -c "
                "\"import secrets; print(secrets.token_urlsafe(48))\"`."
            )


# Global settings instance
settings = Settings()
