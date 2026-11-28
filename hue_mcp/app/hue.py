"""Small client for the local Philips Hue Bridge API (CLIP v2, plus v1 for pairing)."""
from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

LOG = logging.getLogger("hue_mcp.hue")
DEVICE_TYPE = "hue_mcp#homeassistant"


class ToolError(Exception):
    """Error message meant for Claude."""


def _ctx() -> ssl.SSLContext:
    # The bridge uses a certificate signed by Signify's own CA for its bridge ID, not a
    # public one. It is only ever contacted inside the home network.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class Hue:
    def __init__(self, host: str, store: Path, scheme: str = "https"):
        self.configured_host = host.strip()
        self.store = store
        self.scheme = scheme
        self._lock = threading.Lock()
        self._last_call = 0.0
        self.state = self._load()
        if self.configured_host:
            self.state["host"] = self.configured_host

    # ---------------------------------------------------------------- storage
    def _load(self) -> dict:
        try:
            return json.loads(self.store.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        tmp = self.store.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state))
        os.chmod(tmp, 0o600)
        tmp.rename(self.store)

    @property
    def host(self) -> str:
        return self.state.get("host", "")

    @property
    def paired(self) -> bool:
        return bool(self.state.get("app_key"))

    # ---------------------------------------------------------------- http
    def _http(self, method: str, url: str, body=None, headers: dict | None = None, timeout: int = 15):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, method=method, data=data,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"errors": [{"description": raw[:300].decode("utf-8", "replace")}]}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ToolError(f"Hue Bridge at {self.host or '?'} not reachable: {e}") from None

    def discover(self) -> str:
        """Find the bridge via Signify's discovery service (needs internet)."""
        try:
            req = urllib.request.Request("https://discovery.meethue.com/")
            with urllib.request.urlopen(req, timeout=10) as r:
                found = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise ToolError(f"Bridge discovery failed ({e}). Set bridge_host in the app options.") from None
        if not found:
            raise ToolError("No Hue Bridge found. Set bridge_host in the app options.")
        ip = found[0].get("internalipaddress", "")
        if not ip:
            raise ToolError("Discovery returned no IP. Set bridge_host in the app options.")
        if self.state.get("host") != ip:
            self.state["host"] = ip
            self._save()
        return ip

    def _ensure_host(self) -> str:
        return self.host or self.discover()

    # ---------------------------------------------------------------- pairing
    def pair(self) -> dict:
        host = self._ensure_host()
        status, res = self._http("POST", f"{self.scheme}://{host}/api",
                                 {"devicetype": DEVICE_TYPE, "generateclientkey": True})
        item = res[0] if isinstance(res, list) and res else {}
        if "success" in item:
            self.state["app_key"] = item["success"]["username"]
            self._save()
            info = self.bridge_info()
            self.state["bridge_id"] = info.get("bridge_id", "")
            self._save()
            return {"paired": True, "host": host, **info}
        err = (item.get("error") or {})
        if err.get("type") == 101:
            raise ToolError("Link button not pressed. Ask the user to press the round button on the "
                            "Hue Bridge, then call pair again within 30 seconds.")
        raise ToolError(f"Pairing failed: {err.get('description') or res}")

    def forget(self) -> None:
        self.state.pop("app_key", None)
        self._save()

    # ---------------------------------------------------------------- CLIP v2
    def request(self, method: str, path: str, body=None) -> list:
        if not self.paired:
            raise ToolError("Not paired with the Hue Bridge yet. Ask the user to press the button "
                            "on the bridge, then call pair.")
        host = self._ensure_host()
        with self._lock:  # the bridge dislikes bursts; keep ≥ 100 ms between calls
            wait = 0.1 - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            status, res = self._http(method, f"{self.scheme}://{host}/clip/v2/{path.lstrip('/')}",
                                     body, {"hue-application-key": self.state["app_key"]})
            self._last_call = time.monotonic()
        errors = [e.get("description", str(e)) for e in (res.get("errors") or [])] \
            if isinstance(res, dict) else []
        if status == 403 or status == 401:
            raise ToolError("The bridge rejected the app key (maybe removed in the Hue app). "
                            "Call pair again after the user pressed the bridge button.")
        if status >= 400 or (errors and not res.get("data")):
            raise ToolError(f"Hue Bridge error {status}: {'; '.join(errors) or res}")
        if errors:
            LOG.warning("Bridge warnings for %s %s: %s", method, path, errors)
        return res.get("data", []) if isinstance(res, dict) else []

    def get(self, rtype: str, rid: str | None = None) -> list:
        return self.request("GET", f"resource/{rtype}" + (f"/{rid}" if rid else ""))

    def put(self, rtype: str, rid: str, body: dict) -> list:
        return self.request("PUT", f"resource/{rtype}/{rid}", body)

    def post(self, rtype: str, body: dict) -> list:
        return self.request("POST", f"resource/{rtype}", body)

    def delete(self, rtype: str, rid: str) -> list:
        return self.request("DELETE", f"resource/{rtype}/{rid}")

    def bridge_info(self) -> dict:
        b = self.get("bridge")
        cfg_status, cfg = self._http("GET", f"{self.scheme}://{self.host}/api/0/config")
        out = {"bridge_id": b[0].get("bridge_id", "") if b else ""}
        if isinstance(cfg, dict):
            out.update({k: cfg.get(k) for k in ("name", "modelid", "swversion", "apiversion") if k in cfg})
        return out

    def search_new_devices(self) -> str:
        disc = self.get("zigbee_device_discovery")
        if disc:
            self.put("zigbee_device_discovery", disc[0]["id"],
                     {"action": {"action_type": "search"}})
            return "v2"
        # Older bridge firmware: v1 search
        self._http("POST", f"{self.scheme}://{self.host}/api/{self.state['app_key']}/lights", {})
        return "v1"
