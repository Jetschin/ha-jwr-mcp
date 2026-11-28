"""User-facing texts (Home Assistant notifications) in English and German.

Texts meant for Claude (tool descriptions, errors) are English only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

TEXTS: dict[str, dict[str, str]] = {
    "n_restart_title": {"en": "Hue MCP: restart required", "de": "Hue MCP: Neustart nötig"},
    "n_restart_msg": {
        "en": "The app installed the integration “Hue MCP Bridge”. Please restart Home Assistant "
              "once (Settings → System → Restart). The bridge then sets itself up.",
        "de": "Die App hat die Integration „Hue MCP Bridge“ installiert. Bitte Home Assistant "
              "einmal neu starten (Einstellungen → System → Neu starten). Danach richtet sich die "
              "Brücke automatisch ein."},
    "n_updated_msg": {
        "en": "The bridge integration was updated. Please restart Home Assistant "
              "(Settings → System → Restart).",
        "de": "Die Brücken-Integration wurde aktualisiert. Bitte Home Assistant neu starten "
              "(Einstellungen → System → Neu starten)."},
    "n_pair_title": {"en": "Hue MCP: pair with the Hue Bridge", "de": "Hue MCP: mit der Hue Bridge koppeln"},
    "n_pair_msg": {
        "en": "Press the round button on top of the Hue Bridge. Within 30 seconds the app pairs "
              "automatically (or ask Claude to pair).",
        "de": "Drück den runden Knopf oben auf der Hue Bridge. Die App koppelt sich innerhalb von "
              "30 Sekunden automatisch (oder bitte Claude, zu koppeln)."},
    "n_paired_title": {"en": "Hue MCP paired", "de": "Hue MCP gekoppelt"},
    "n_paired_msg": {"en": "Connected to Hue Bridge {bridge}.", "de": "Mit Hue Bridge {bridge} verbunden."},
}


def _language() -> str:
    lang = os.environ.get("HUE_LANGUAGE")
    if not lang:
        p = Path(os.environ.get("HUE_OPTIONS", "/data/options.json"))
        try:
            lang = json.loads(p.read_text()).get("language")
        except (OSError, ValueError):
            lang = None
    return lang if lang in ("en", "de") else "en"


LANG = _language()


def t(key: str, **kw) -> str:
    entry = TEXTS[key]
    return entry.get(LANG, entry["en"]).format(**kw)
