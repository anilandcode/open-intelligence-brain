"""Hermes messaging pairing — send Brain updates through Hermes.

This module pairs the Brain with Hermes so routine digests, alerts, and
notifications flow through the same messaging surface the user already uses.

Configuration:
    BRAIN_HERMES_URL=http://localhost:5177  # Hermes API
    BRAIN_HERMES_CHANNEL=digital-brain      # Channel name in Hermes

The pairing is optional — without it, routines log to stdout.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger("brain.messaging")


@dataclass
class HermesConfig:
    """Configuration for Hermes messaging."""
    api_url: str = ""
    channel: str = "digital-brain"
    timeout: float = 10.0

    @classmethod
    def from_env(cls) -> HermesConfig:
        return cls(
            api_url=os.environ.get("BRAIN_HERMES_URL", ""),
            channel=os.environ.get("BRAIN_HERMES_CHANNEL", "digital-brain"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_url)


class HermesMessenger:
    """Send messages through Hermes."""

    def __init__(self, config: HermesConfig | None = None):
        self.config = config or HermesConfig.from_env()

    def send(self, message: str, channel: str | None = None) -> bool:
        """Send a message through Hermes.

        Returns True if delivered, False if failed or not configured.
        """
        if not self.config.configured:
            logger.debug("Hermes not configured, logging instead:\n%s", message)
            return False

        target = channel or self.config.channel
        try:
            response = httpx.post(
                f"{self.config.api_url}/api/v1/send",
                json={"channel": target, "message": message},
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            logger.info("Sent message to Hermes channel '%s'", target)
            return True
        except Exception as exc:
            logger.warning("Hermes send failed: %s", exc)
            return False

    def send_routine(self, formatted_digest: str) -> bool:
        """Send a routine digest."""
        return self.send(formatted_digest)

    def send_alert(self, message: str) -> bool:
        """Send an urgent alert."""
        alert = f"🚨 BRAIN ALERT\n{'─' * 30}\n{message}"
        return self.send(alert)

    def test_connection(self) -> bool:
        """Test if Hermes is reachable."""
        if not self.config.configured:
            return False
        try:
            response = httpx.get(
                f"{self.config.api_url}/health",
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception:
            return False