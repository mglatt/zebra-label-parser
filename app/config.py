from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_HA_OPTIONS = Path("/data/options.json")


def _load_ha_options() -> dict:
    """Load Home Assistant addon options if available."""
    if _HA_OPTIONS.is_file():
        return json.loads(_HA_OPTIONS.read_text())
    return {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZLP_", env_file=".env", extra="ignore")

    # Claude API
    anthropic_api_key: Optional[str] = None
    claude_model: str = "claude-sonnet-4-20250514"

    # Printer
    printer_name: Optional[str] = None
    cups_server: Optional[str] = None

    # Label dimensions (4x6" at 203 DPI)
    label_width_inches: float = 4.0
    label_height_inches: float = 6.0
    label_dpi: int = 203

    # Server
    host: str = "0.0.0.0"
    port: int = 8099

    @property
    def label_width_px(self) -> int:
        return int(self.label_width_inches * self.label_dpi)

    @property
    def label_height_px(self) -> int:
        return int(self.label_height_inches * self.label_dpi)

    def model_post_init(self, __context) -> None:
        # Overlay HA options onto env-sourced values
        ha = _load_ha_options()
        if ha.get("anthropic_api_key") and not self.anthropic_api_key:
            self.anthropic_api_key = ha["anthropic_api_key"]
        if ha.get("printer_name") and not self.printer_name:
            self.printer_name = ha["printer_name"]
        if ha.get("claude_model"):
            self.claude_model = ha["claude_model"]


def get_settings() -> Settings:
    return Settings()
