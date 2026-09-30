"""Configuration module for Pack Manager rules and confidence thresholds.

Ensures thresholds live in config, not scattered across code (context.md Section 5).
Includes versioning for audit trail logging (context.md Section 14).
"""

from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RulesThresholdConfig:
    count_confidence_threshold: float = 0.70
    identity_confidence_threshold: float = 0.75
    version: str = "v1.0.0"

    @classmethod
    def from_env(cls) -> RulesThresholdConfig:
        """Loads configuration from environment variables with sensible defaults."""
        return cls(
            count_confidence_threshold=float(os.getenv("CONF_COUNT_THRESHOLD", "0.70")),
            identity_confidence_threshold=float(os.getenv("CONF_IDENTITY_THRESHOLD", "0.75")),
            version=os.getenv("THRESHOLD_CONFIG_VERSION", "v1.0.0")
        )


# Global default configuration instance
DEFAULT_CONFIG = RulesThresholdConfig.from_env()
