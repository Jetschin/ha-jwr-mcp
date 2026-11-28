"""Background setup:

1. Create secrets (webhook ID, internal token) in /data/secrets.json.
2. Copy the small HA integration ``hue_mcp_bridge`` to /config/custom_components.
   It registers an HA webhook and forwards MCP requests to this app, so the server
   is reachable through Home Assistant's existing HTTPS address (DuckDNS, Nabu Casa,
   reverse proxy) without opening an extra port.
3. Write /config/.hue_mcp_bridge.json (target URL + token for the integration).
4. Create or reload the integration's config entry.
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

from i18n import t

LOG = logging.getLogger("hue_mcp.bootstrap")
DOMAIN = "hue_mcp_bridge"
SRC_INTEGRATION = Path(__file__).resolve().parent.parent / "integration" / DOMAIN
DST_INTEGRATION = Path("/config/custom_components") / DOMAIN
BRIDGE_CONFIG = Path("/config/.hue_mcp_bridge.json")


SECRETS_VERSION = 2
ID_LEN = 100
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def random_key(n: int) -> str:
    """Random string of letters and digits (cryptographically secure)."""
    return "".join(pysecrets.choice(ALPHABET) for _ in range(n))


def load_secrets(data_dir: Path, rotate: bool = False) -> dict:
    p = data_dir / "secrets.json"
    marker = data_dir / ".rotated"
    if not rotate and marker.exists():
        marker.unlink()
    if rotate and marker.exists():  # rotate only once per switch-on
        rotate = False
    elif rotate:
        marker.touch()
    if p.exists() and not rotate:
        try:
            old = json.loads(p.read_text())
            if old.get("version") == SECRETS_VERSION:
                return old
            LOG.warning("Old webhook address replaced by a new one with %d characters. "
                        "Update the connector in claude.ai with the new URL.", ID_LEN)
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
        LOG.warning("New webhook address and token generated (rotate_secret). "
                    "Re-create the connector in claude.ai with the new URL and "
                    "switch rotate_secret off again.")
    return s


def _core_api(method: str, path: str, data: dict | None = None):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None, "no SUPERVISOR_TOKEN"
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
    """Copy the integration. True if anything changed."""
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
    url = f"{opts['external_url'] or 'https://<external-ha-address>'}/api/webhook/{secrets['webhook_id']}"
    try:
        changed_code = install_integration()
    except OSError as e:
        LOG.error("Could not install the integration: %s", e)
        return
    client_key = (opts.get("client_key") or "").strip()
    if not client_key:
        LOG.warning("No header key (client_key) set – the connector URL alone grants access. "
                    "Recommended: set client_key and add it in claude.ai as header x-api-key.")
    elif len(client_key) < 32:
        LOG.warning("client_key is shorter than 32 characters – please choose a longer one.")
    changed_cfg = write_bridge_config(secrets, opts["port"], client_key)
    restart_hint_sent = False
    while True:
        entries, err = _entries()
        if entries is None:
            LOG.info("Home Assistant not reachable yet (%s) – retrying in 30 s", err)
            time.sleep(30)
            continue
        if entries:
            if changed_code:
                LOG.warning("Integration updated – please restart Home Assistant.")
                _notify("Hue MCP", t("n_updated_msg"), "hue_mcp_restart")
            elif changed_cfg:
                eid = entries[0]["entry_id"]
                _core_api("POST", f"/config/config_entries/entry/{eid}/reload")
                LOG.info("Bridge reloaded.")
            break
        res, err = _core_api("POST", "/config/config_entries/flow", {"handler": DOMAIN})
        if isinstance(res, dict) and res.get("type") in ("create_entry", "abort"):
            LOG.info("Bridge set up in Home Assistant.")
            break
        if not restart_hint_sent:
            LOG.warning("Integration not loaded yet (%s). Restart Home Assistant once; "
                        "setup continues automatically afterwards.", err)
            _notify(t("n_restart_title"), t("n_restart_msg"), "hue_mcp_restart")
            restart_hint_sent = True
        time.sleep(30)
    LOG.info("=" * 70)
    LOG.info("Connector URL for claude.ai (keep it secret):")
    LOG.info("  %s", url)
    if client_key:
        LOG.info("Also required: header x-api-key = value of the option client_key "
                 "(not shown here).")
    LOG.info("=" * 70)


def start_background(opts: dict, secrets: dict) -> None:
    threading.Thread(target=_worker, args=(opts, secrets), daemon=True).start()


def notify(title: str, message: str, nid: str) -> None:
    """Persistent notification in Home Assistant."""
    threading.Thread(target=_notify, args=(title, message, nid), daemon=True).start()


def dismiss_notification(nid: str) -> None:
    threading.Thread(target=_core_api, daemon=True,
                     args=("POST", "/services/persistent_notification/dismiss",
                           {"notification_id": nid})).start()
