"""iCloud-Zugriff über pyicloud: Anmeldung (mit 2FA) und Lesen aus iCloud Drive.

Das Apple-Passwort wird nie gespeichert. Nach erfolgreicher 2FA liegt in
/data/session nur die vertrauenswürdige Sitzung (Cookies/Token), die Apple
etwa zwei Monate gelten lässt.
"""
from __future__ import annotations

import io
import logging
import os
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

LOG = logging.getLogger("icloud_mcp.icloud")


class ToolError(Exception):
    """Fehler mit verständlicher Meldung für Claude."""


LOGIN_HINT = ("Die iCloud-Anmeldung ist abgelaufen oder fehlt. In Home Assistant in der "
              "Seitenleiste „iCloud“ öffnen und neu anmelden (Passwort + 2FA-Code).")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


class ICloud:
    """Serialisierter Zugriff auf genau ein iCloud-Konto."""

    def __init__(self, apple_id: str, session_dir: Path, max_bytes: int) -> None:
        self.apple_id = apple_id.strip()
        self.session_dir = session_dir
        self.max_bytes = max_bytes
        self.lock = threading.RLock()
        self._api: Any = None
        self._checked = 0.0
        self._pending: Any = None  # Login wartet auf 2FA-Code
        self._root_at = 0.0
        self.last_status: dict[str, Any] = {"authenticated": False}

    # ------------------------------------------------------------ Sitzung
    def _new_client(self, password: str | None = None) -> Any:
        from pyicloud import PyiCloudService

        self.session_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.session_dir, 0o700)
        if password is None:
            return PyiCloudService(self.apple_id, cookie_directory=str(self.session_dir),
                                   authenticate=False, refresh_interval=None)
        return PyiCloudService(self.apple_id, password, cookie_directory=str(self.session_dir),
                               refresh_interval=None)

    def status(self, force: bool = False) -> dict[str, Any]:
        """Prüft die gespeicherte Sitzung (höchstens alle 5 Minuten bei Apple)."""
        with self.lock:
            if not self.apple_id:
                self.last_status = {"authenticated": False, "reason": "Keine Apple-ID konfiguriert"}
                return self.last_status
            if not force and self._api is not None and time.monotonic() - self._checked < 300:
                return self.last_status
            try:
                if self._api is None:
                    self._api = self._new_client()
                st = self._api.get_auth_status()
            except Exception as e:  # noqa: BLE001
                LOG.warning("iCloud-Statusprüfung fehlgeschlagen: %s", e)
                self._api = None
                self.last_status = {"authenticated": False, "reason": f"iCloud nicht erreichbar: {e}"}
                return self.last_status
            ok = bool(st.get("authenticated")) and not st.get("requires_2fa") and not st.get("requires_2sa")
            self.last_status = {"authenticated": ok, "trusted": bool(st.get("trusted_session"))}
            if not ok:
                self.last_status["reason"] = "Anmeldung erforderlich"
            self._checked = time.monotonic()
            return self.last_status

    def api(self) -> Any:
        if not self.status().get("authenticated"):
            raise ToolError(LOGIN_HINT)
        return self._api

    # ------------------------------------------------------------ Login (Ingress)
    def login(self, password: str) -> str:
        """Schritt 1. Rückgabe: 'ok', '2fa' oder Fehlermeldung (beginnt mit 'Fehler')."""
        from pyicloud.exceptions import (PyiCloudAccountLockedException,
                                         PyiCloudFailedLoginException,
                                         PyiCloudNoTrustedNumberAvailable)

        with self.lock:
            self._pending = None
            try:
                api = self._new_client(password)
            except PyiCloudAccountLockedException:
                return "Fehler: Apple-Account ist gesperrt. Bitte unter iforgot.apple.com entsperren."
            except PyiCloudFailedLoginException:
                return "Fehler: Apple-ID oder Passwort falsch."
            except Exception as e:  # noqa: BLE001
                LOG.warning("Login fehlgeschlagen: %s", type(e).__name__)
                return f"Fehler: Anmeldung fehlgeschlagen ({type(e).__name__})."
            if api.requires_2sa and not api.requires_2fa:
                return "Fehler: Dein Account nutzt die alte zweistufige Bestätigung – wird nicht unterstützt."
            if not api.requires_2fa:
                if not api.is_trusted_session:
                    api.trust_session()
                self._activate(api)
                return "ok"
            try:
                needs_key = bool(getattr(api, "security_key_names", None))
            except Exception:  # noqa: BLE001
                needs_key = False
            if needs_key:
                return ("Fehler: Dein Account verlangt einen Hardware-Sicherheitsschlüssel. "
                        "Das geht hier nicht.")
            try:
                if not api.request_2fa_code():
                    return "Fehler: Apple verlangt einen Sicherheitsschlüssel."
            except PyiCloudNoTrustedNumberAvailable:
                return "Fehler: Keine vertrauenswürdige Telefonnummer im Apple-Account."
            except Exception:  # noqa: BLE001
                # Code wird oft trotzdem auf dem iPhone angezeigt
                try:
                    api.use_existing_trusted_device_code()
                except Exception:  # noqa: BLE001
                    pass
            self._pending = api
            return "2fa"

    def verify(self, code: str) -> str:
        """Schritt 2: 2FA-Code prüfen und Sitzung vertrauen."""
        with self.lock:
            api = self._pending
            if api is None:
                return "Fehler: Bitte zuerst das Passwort eingeben."
            code = "".join(ch for ch in code if ch.isdigit())
            if len(code) != 6:
                return "Fehler: Der Code hat 6 Ziffern."
            try:
                valid = api.validate_2fa_code(code)
            except Exception as e:  # noqa: BLE001
                LOG.warning("2FA-Prüfung fehlgeschlagen: %s", type(e).__name__)
                valid = False
            if not valid:
                return "Fehler: Code ungültig. Bitte erneut eingeben."
            if not api.is_trusted_session:
                api.trust_session()
            self._pending = None
            self._activate(api)
            return "ok"

    def _activate(self, api: Any) -> None:
        try:
            api._password_raw = None  # noqa: SLF001 – Passwort nicht im Speicher halten
        except AttributeError:
            pass
        self._api = api
        self._checked = 0.0
        self._root_at = 0.0
        self.status(force=True)
        LOG.info("iCloud-Anmeldung erfolgreich (vertrauenswürdige Sitzung gespeichert).")

    def logout(self) -> None:
        with self.lock:
            self._api = None
            self._pending = None
            for f in self.session_dir.glob("*"):
                if f.is_file():
                    f.unlink()
            self.last_status = {"authenticated": False, "reason": "Abgemeldet"}

    @property
    def awaiting_code(self) -> bool:
        return self._pending is not None

    # ------------------------------------------------------------ Drive
    @staticmethod
    def parts(path: str | None) -> list[str]:
        p = (path or "").replace("\\", "/")
        for prefix in ("iCloud Drive/", "iCloud-Drive/"):
            if p.startswith(prefix):
                p = p[len(prefix):]
        parts = [x for x in p.split("/") if x not in ("", ".")]
        if ".." in parts:
            raise ToolError("'..' ist in Pfaden nicht erlaubt.")
        return parts

    def node(self, path: str | None) -> Any:
        with self.lock:
            drive = self.api().drive
            if time.monotonic() - self._root_at > 60:  # Ordnerbaum höchstens 1 min alt
                drive.refresh_root()
                self._root_at = time.monotonic()
            node = drive.root
            walked: list[str] = []
            for part in self.parts(path):
                if node.type == "file":
                    raise ToolError(f"'{'/'.join(walked)}' ist eine Datei, kein Ordner.")
                kids = node.get_children()
                hit = next((c for c in kids if c.name == part), None) or \
                    next((c for c in kids if _nfc(c.name) == _nfc(part)), None)
                if hit is None:
                    raise ToolError(f"'{part}' gibt es nicht in {'/'.join(walked) or 'iCloud Drive'}.")
                node = hit
                walked.append(hit.name)
            return node

    def children(self, node: Any, refresh: bool = True) -> list[Any]:
        with self.lock:
            return list(node.get_children(force=refresh))

    def download(self, node: Any, limit: int | None = None) -> bytes:
        limit = limit or self.max_bytes
        with self.lock:
            if node.type != "file":
                raise ToolError(f"'{node.name}' ist ein Ordner.")
            size = node.size or 0
            if size > limit:
                raise ToolError(f"Datei ist {size / 1048576:.1f} MB groß (Limit {limit // 1048576} MB).")
            resp = node.open(stream=True)
            buf = io.BytesIO()
            for chunk in resp.iter_content(chunk_size=1 << 16):
                buf.write(chunk)
                if buf.tell() > limit:
                    raise ToolError("Datei überschreitet das Lese-Limit.")
            return buf.getvalue()
