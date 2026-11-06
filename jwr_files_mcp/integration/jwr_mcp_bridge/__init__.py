"""JWR MCP Bridge – leitet einen Home-Assistant-Webhook an das Add-on
"JWR Dateien MCP" weiter.

Wird vom Add-on automatisch installiert und konfiguriert. Die Webhook-ID ist
ein langer Zufallswert und dient als Zugangsschlüssel; zwischen Integration und
Add-on wird zusätzlich ein internes Bearer-Token verwendet.
"""
from __future__ import annotations

import hmac
import json
import logging
from pathlib import Path

import aiohttp
from aiohttp import web

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)
DOMAIN = "jwr_mcp_bridge"
CONFIG_FILE = Path("/config/.jwr_mcp_bridge.json")
MAX_BODY = 30 * 1024 * 1024
PASS_HEADERS = ("Mcp-Session-Id", "Mcp-Protocol-Version", "Last-Event-ID")
KEY_HEADER = "X-Api-Key"


def _read_config() -> dict | None:
    if not CONFIG_FILE.exists():
        return None
    return json.loads(CONFIG_FILE.read_text())


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    cfg = await hass.async_add_executor_job(_read_config)
    if not cfg or not cfg.get("webhook_id") or not cfg.get("target_url"):
        raise ConfigEntryNotReady("Konfiguration vom Add-on fehlt – Add-on starten.")
    hass.data[DOMAIN] = {
        "webhook_id": cfg["webhook_id"],
        "target_url": cfg["target_url"],
        "token": cfg["token"],
        "client_key": cfg.get("client_key") or "",
    }
    if not hass.data[DOMAIN]["client_key"]:
        _LOGGER.warning("JWR MCP Bridge: kein Header-Schlüssel gesetzt – nur die URL schützt den Zugang.")
    webhook.async_register(
        hass, DOMAIN, "JWR Dateien MCP", cfg["webhook_id"], _handle_webhook,
        allowed_methods=["POST", "GET"],
    )
    _LOGGER.info("JWR MCP Bridge aktiv (Webhook %s…)", cfg["webhook_id"][:8])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.pop(DOMAIN, None)
    if data:
        webhook.async_unregister(hass, data["webhook_id"])
    return True


async def _handle_webhook(hass: HomeAssistant, webhook_id: str, request: web.Request):
    data = hass.data.get(DOMAIN)
    if not data or webhook_id != data["webhook_id"]:
        return web.Response(status=200)
    if data["client_key"]:
        sent = request.headers.get(KEY_HEADER, "")
        if not hmac.compare_digest(sent.encode(), data["client_key"].encode()):
            # Antwort wie bei einem unbekannten Webhook – verrät nichts.
            _LOGGER.warning("JWR MCP Bridge: Anfrage ohne gültigen %s von %s abgewiesen",
                            KEY_HEADER, request.remote)
            return web.Response(status=200)
    if request.method != "POST":
        return web.Response(status=405, headers={"Allow": "POST"})
    if request.content_length and request.content_length > MAX_BODY:
        return web.Response(status=413)
    body = await request.read()
    headers = {
        "Authorization": f"Bearer {data['token']}",
        "Content-Type": request.headers.get("Content-Type", "application/json"),
        "Accept": "application/json",
    }
    for h in PASS_HEADERS:
        if h in request.headers:
            headers[h] = request.headers[h]
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            data["target_url"], data=body, headers=headers,
            timeout=aiohttp.ClientTimeout(total=300, connect=10),
        ) as resp:
            payload = await resp.read()
            out_headers = {"Cache-Control": "no-store"}
            if "Mcp-Session-Id" in resp.headers:
                out_headers["Mcp-Session-Id"] = resp.headers["Mcp-Session-Id"]
            if resp.status == 202 or not payload:
                return web.Response(status=resp.status, headers=out_headers)
            return web.Response(status=resp.status, body=payload,
                                content_type="application/json", headers=out_headers)
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.warning("JWR MCP Bridge: Add-on nicht erreichbar: %s", err)
        return web.Response(status=502, text="JWR Dateien MCP nicht erreichbar")
