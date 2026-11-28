"""Config flow without a form – triggered automatically by the app."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

DOMAIN = "hue_mcp_bridge"


class HueMcpBridgeFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Hue MCP", data={})

    async def async_step_import(self, import_data: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_user()
