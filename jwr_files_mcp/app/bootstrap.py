"""Einrichtung im Hintergrund:

1. Geheimnisse (Webhook-ID, internes Token) in /data/secrets.json anlegen.
2. Die kleine HA-Integration ``jwr_mcp_bridge`` nach /config/custom_components
   kopieren. Sie registriert einen HA-Webhook und leitet MCP-Anfragen an dieses
   Add-on weiter. So ist der Server über die vorhandene HTTPS-Adresse von Home
   Assistant erreichbar (DuckDNS/Nabu Casa), ohne zusätzliche Portfreigabe.
3. /config/.jwr_mcp_bridge.json schreiben (Ziel-URL + Token für die Integration).
4. Den Config-Entry der Integration anlegen bzw. neu laden.
"""
from __future__ import annotations

import filecmp
import hashlib
import json
import logging
import os
import secrets as pysecrets
import shutil
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

LOG = logging.getLogger("jwr_mcp.bootstrap")
DOMAIN = "jwr_mcp_bridge"
SRC_INTEGRATION = Path(__file__).resolve().parent.parent / "integration" / DOMAIN
DST_INTEGRATION = Path("/config/custom_components") / DOMAIN
BRIDGE_CONFIG = Path("/config/.jwr_mcp_bridge.json")


SECRETS_VERSION = 2
ID_LEN = 100
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def random_key(n: int) -> str:
    """Zufallskette aus Buchstaben und Ziffern (kryptografisch sicher)."""
    return "".join(pysecrets.choice(ALPHABET) for _ in range(n))


def load_secrets(data_dir: Path, rotate: bool = False) -> dict:
    p = data_dir / "secrets.json"
    marker = data_dir / ".rotated"
    if not rotate and marker.exists():
        marker.unlink()
    if rotate and marker.exists():  # nur einmal pro Einschalten rotieren
        rotate = False
    elif rotate:
        marker.touch()
    if p.exists() and not rotate:
        try:
            old = json.loads(p.read_text())
            if old.get("version") == SECRETS_VERSION:
                return old
            LOG.warning("Alte Webhook-Adresse wird durch eine neue mit %d Zeichen ersetzt. "
                        "Connector in claude.ai mit der neuen URL aktualisieren.", ID_LEN)
        except (OSError, json.JSONDecodeError):
            pass
    s = {
        "version": SECRETS_VERSION,
        "webhook_id": random_key(ID_LEN),
        "token": random_key(64),
    }
    p.write_text(json.dumps(s))
    os.chmod(p, 0o600)
    if rotate:
        LOG.warning("Neue Webhook-Adresse und neues Token erzeugt (rotate_secret). "
                    "Connector in claude.ai mit der neuen URL neu anlegen und "
                    "die Option rotate_secret wieder ausschalten.")
    return s


def _core_api(method: str, path: str, data: dict | None = None):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None, "kein SUPERVISOR_TOKEN"
    req = urllib.request.Request(
        f"http://supervisor/core/api{path}", method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            return (json.loads(body) if body else {}), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:200]!r}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return None, str(e)


def _dir_hash(p: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            h.update(str(f.relative_to(p)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def install_integration() -> bool:
    """Kopiert die Integration. True, wenn sich etwas geändert hat."""
    if DST_INTEGRATION.exists() and _dir_hash(DST_INTEGRATION) == _dir_hash(SRC_INTEGRATION):
        return False
    DST_INTEGRATION.parent.mkdir(parents=True, exist_ok=True)
    tmp = DST_INTEGRATION.with_name(DOMAIN + ".new")
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(SRC_INTEGRATION, tmp, ignore=shutil.ignore_patterns("__pycache__"))
    if DST_INTEGRATION.exists():
        shutil.rmtree(DST_INTEGRATION)
    tmp.rename(DST_INTEGRATION)
    return True


def _own_ip() -> str:
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return socket.gethostname()


def write_bridge_config(secrets: dict, port: int, client_key: str = "") -> bool:
    cfg = {
        "webhook_id": secrets["webhook_id"],
        "token": secrets["token"],
        "target_url": f"http://{_own_ip()}:{port}/mcp",
        "client_key": client_key,
    }
    old = None
    if BRIDGE_CONFIG.exists():
        try:
            old = json.loads(BRIDGE_CONFIG.read_text())
        except (OSError, json.JSONDecodeError):
            old = None
    if old == cfg:
        return False
    tmp = BRIDGE_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg))
    os.chmod(tmp, 0o600)
    tmp.rename(BRIDGE_CONFIG)
    return True


def _entries():
    res, err = _core_api("GET", "/config/config_entries/entry")
    if res is None:
        return None, err
    return [e for e in res if isinstance(e, dict) and e.get("domain") == DOMAIN], None


def _notify(title: str, message: str, nid: str) -> None:
    _core_api("POST", "/services/persistent_notification/create",
              {"title": title, "message": message, "notification_id": nid})


def _worker(opts: dict, secrets: dict) -> None:
    url = f"{opts['external_url'] or 'https://<externe-ha-adresse>'}/api/webhook/{secrets['webhook_id']}"
    try:
        changed_code = install_integration()
    except OSError as e:
        LOG.error("Integration konnte nicht installiert werden: %s", e)
        return
    client_key = (opts.get("client_key") or "").strip()
    if not client_key:
        LOG.warning("Kein Header-Schlüssel (client_key) gesetzt – die Connector-URL allein "
                    "gewährt Zugriff. Empfohlen: client_key setzen und in claude.ai als "
                    "Header x-api-key eintragen.")
    elif len(client_key) < 32:
        LOG.warning("client_key ist kürzer als 32 Zeichen – bitte länger wählen.")
    changed_cfg = write_bridge_config(secrets, opts["port"], client_key)
    restart_hint_sent = False
    while True:
        entries, err = _entries()
        if entries is None:
            LOG.info("Home Assistant noch nicht erreichbar (%s) – neuer Versuch in 30 s", err)
            time.sleep(30)
            continue
        if entries:
            if changed_code:
                LOG.warning("Integration aktualisiert – Home Assistant bitte neu starten.")
                _notify("JWR Dateien MCP", "Die Brücken-Integration wurde aktualisiert. "
                        "Bitte Home Assistant neu starten (Einstellungen → System → Neu starten).",
                        "jwr_mcp_restart")
            elif changed_cfg:
                eid = entries[0]["entry_id"]
                _core_api("POST", f"/config/config_entries/entry/{eid}/reload")
                LOG.info("Brücke neu geladen.")
            break
        res, err = _core_api("POST", "/config/config_entries/flow", {"handler": DOMAIN})
        if isinstance(res, dict) and res.get("type") in ("create_entry", "abort"):
            LOG.info("Brücke in Home Assistant eingerichtet.")
            break
        if not restart_hint_sent:
            LOG.warning("Integration noch nicht geladen (%s). Home Assistant einmal neu "
                        "starten; die Einrichtung läuft danach automatisch weiter.", err)
            _notify("JWR Dateien MCP: Neustart nötig",
                    "Das Add-on hat die Integration „JWR MCP Bridge“ installiert. Bitte Home "
                    "Assistant einmal neu starten (Einstellungen → System → Neu starten). "
                    "Danach richtet sich die Brücke automatisch ein.", "jwr_mcp_restart")
            restart_hint_sent = True
        time.sleep(30)
    LOG.info("=" * 70)
    LOG.info("Connector-URL für claude.ai (geheim halten):")
    LOG.info("  %s", url)
    if client_key:
        LOG.info("Zusätzlich nötig: Header x-api-key = Wert der Option client_key "
                 "(wird hier nicht angezeigt).")
    LOG.info("=" * 70)


def start_background(opts: dict, secrets: dict) -> None:
    threading.Thread(target=_worker, args=(opts, secrets), daemon=True).start()
