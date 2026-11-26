"""iCloud access via pyicloud: sign-in (with 2FA) and read-only iCloud Drive access.

The Apple password is never stored. After a successful 2FA confirmation only the
trusted session (cookies/token) is kept in /data/session; Apple honours it for
roughly two months.
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

from i18n import t

LOG = logging.getLogger("icloud_mcp.icloud")


class ToolError(Exception):
    """Error with a message meant for Claude."""


LOGIN_HINT = ("The iCloud sign-in has expired or is missing. Ask the user to open “iCloud” in "
              "the Home Assistant sidebar and sign in again (password + 2FA code).")


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


class ICloud:
    """Serialised access to exactly one iCloud account."""

    def __init__(self, apple_id: str, session_dir: Path, max_bytes: int) -> None:
        self.apple_id = apple_id.strip()
        self.session_dir = session_dir
        self.max_bytes = max_bytes
        self.lock = threading.RLock()
        self._api: Any = None
        self._checked = 0.0
        self._pending: Any = None  # sign-in waiting for the 2FA code
        self._root_at = 0.0
        self.last_status: dict[str, Any] = {"authenticated": False}

    # ------------------------------------------------------------ session
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
        """Check the stored session (asks Apple at most every 5 minutes)."""
        with self.lock:
            if not self.apple_id:
                self.last_status = {"authenticated": False, "reason": t("no_apple_id")}
                return self.last_status
            if not force and self._api is not None and time.monotonic() - self._checked < 300:
                return self.last_status
            try:
                if self._api is None:
                    self._api = self._new_client()
                st = self._api.get_auth_status()
            except Exception as e:  # noqa: BLE001
                LOG.warning("iCloud status check failed: %s", e)
                self._api = None
                self.last_status = {"authenticated": False, "reason": t("unreachable", err=e)}
                return self.last_status
            ok = bool(st.get("authenticated")) and not st.get("requires_2fa") and not st.get("requires_2sa")
            self.last_status = {"authenticated": ok, "trusted": bool(st.get("trusted_session"))}
            if not ok:
                self.last_status["reason"] = t("sign_in_required")
            self._checked = time.monotonic()
            return self.last_status

    def api(self) -> Any:
        if not self.status().get("authenticated"):
            raise ToolError(LOGIN_HINT)
        return self._api

    # ------------------------------------------------------------ sign-in (ingress page)
    def login(self, password: str) -> tuple[str, str]:
        """Step 1. Returns ('ok'|'2fa'|'error', message)."""
        from pyicloud.exceptions import (PyiCloudAccountLockedException,
                                         PyiCloudFailedLoginException,
                                         PyiCloudNoTrustedNumberAvailable)

        with self.lock:
            self._pending = None
            try:
                api = self._new_client(password)
            except PyiCloudAccountLockedException:
                return "error", t("err_locked")
            except PyiCloudFailedLoginException:
                return "error", t("err_bad_login")
            except Exception as e:  # noqa: BLE001
                LOG.warning("Sign-in failed: %s", type(e).__name__)
                return "error", t("err_login", err=type(e).__name__)
            if api.requires_2sa and not api.requires_2fa:
                return "error", t("err_2sa")
            if not api.requires_2fa:
                if not api.is_trusted_session:
                    api.trust_session()
                self._activate(api)
                return "ok", ""
            try:
                needs_key = bool(getattr(api, "security_key_names", None))
            except Exception:  # noqa: BLE001
                needs_key = False
            if needs_key:
                return "error", t("err_key")
            try:
                if not api.request_2fa_code():
                    return "error", t("err_key")
            except PyiCloudNoTrustedNumberAvailable:
                return "error", t("err_no_phone")
            except Exception:  # noqa: BLE001
                # the code is usually shown on the iPhone anyway
                try:
                    api.use_existing_trusted_device_code()
                except Exception:  # noqa: BLE001
                    pass
            self._pending = api
            return "2fa", ""

    def verify(self, code: str) -> tuple[str, str]:
        """Step 2: check the 2FA code and trust the session."""
        with self.lock:
            api = self._pending
            if api is None:
                return "error", t("err_no_pending")
            code = "".join(ch for ch in code if ch.isdigit())
            if len(code) != 6:
                return "error", t("err_code_len")
            try:
                valid = api.validate_2fa_code(code)
            except Exception as e:  # noqa: BLE001
                LOG.warning("2FA verification failed: %s", type(e).__name__)
                valid = False
            if not valid:
                return "error", t("err_code")
            if not api.is_trusted_session:
                api.trust_session()
            self._pending = None
            self._activate(api)
            return "ok", ""

    def cancel(self) -> None:
        with self.lock:
            self._pending = None

    def _activate(self, api: Any) -> None:
        try:
            api._password_raw = None  # noqa: SLF001 – do not keep the password in memory
        except AttributeError:
            pass
        self._api = api
        self._checked = 0.0
        self._root_at = 0.0
        self.status(force=True)
        LOG.info("iCloud sign-in successful (trusted session stored).")

    def logout(self) -> None:
        with self.lock:
            self._api = None
            self._pending = None
            for f in self.session_dir.glob("*"):
                if f.is_file():
                    f.unlink()
            self.last_status = {"authenticated": False, "reason": t("signed_out")}

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
            raise ToolError("'..' is not allowed in paths.")
        return parts

    def node(self, path: str | None) -> Any:
        with self.lock:
            drive = self.api().drive
            if time.monotonic() - self._root_at > 60:  # folder tree at most 1 min old
                drive.refresh_root()
                self._root_at = time.monotonic()
            node = drive.root
            walked: list[str] = []
            for part in self.parts(path):
                if node.type == "file":
                    raise ToolError(f"'{'/'.join(walked)}' is a file, not a folder.")
                kids = node.get_children()
                hit = next((c for c in kids if c.name == part), None) or \
                    next((c for c in kids if _nfc(c.name) == _nfc(part)), None)
                if hit is None:
                    raise ToolError(f"'{part}' does not exist in {'/'.join(walked) or 'iCloud Drive'}.")
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
                raise ToolError(f"'{node.name}' is a folder.")
            size = node.size or 0
            if size > limit:
                raise ToolError(f"File is {size / 1048576:.1f} MB (limit {limit // 1048576} MB).")
            resp = node.open(stream=True)
            buf = io.BytesIO()
            for chunk in resp.iter_content(chunk_size=1 << 16):
                buf.write(chunk)
                if buf.tell() > limit:
                    raise ToolError("File exceeds the read limit.")
            return buf.getvalue()

    # ------------------------------------------------------------ write (optional)
    BAD_CHARS = set('/\\:') | {chr(c) for c in range(32)}

    def check_name(self, name: str) -> str:
        name = unicodedata.normalize("NFC", (name or "").strip())
        if not name or name in (".", "..") or any(ch in self.BAD_CHARS for ch in name):
            raise ToolError(f"Invalid name: '{name}'.")
        if len(name.encode()) > 255:
            raise ToolError("Name is too long.")
        return name

    def _find(self, folder: Any, name: str, refresh: bool = False) -> Any | None:
        kids = folder.get_children(force=refresh)
        return next((c for c in kids if c.name == name), None) or \
            next((c for c in kids if _nfc(c.name) == _nfc(name)), None)

    def _invalidate(self) -> None:
        self._root_at = 0.0

    def ensure_folder(self, path: str, create: bool) -> Any:
        """Return the folder node for path, creating missing folders if `create`."""
        with self.lock:
            node = self.node("")
            for part in self.parts(path):
                if node.type == "file":
                    raise ToolError(f"'{node.name}' is a file, not a folder.")
                hit = self._find(node, part)
                if hit is None:
                    if not create:
                        raise ToolError(f"Folder '{part}' does not exist (create_dirs=true creates it).")
                    node.mkdir(self.check_name(part))
                    hit = self._find(node, part, refresh=True)
                    if hit is None:
                        raise ToolError(f"Could not create folder '{part}'.")
                    self._invalidate()
                node = hit
            if node.type == "file":
                raise ToolError(f"'{node.name}' is a file, not a folder.")
            return node

    def upload(self, folder: Any, name: str, data: bytes, tmp_dir: Path) -> Any:
        """Upload a new file. Never overwrites an existing one."""
        with self.lock:
            name = self.check_name(name)
            if self._find(folder, name, refresh=True) is not None:
                raise ToolError(f"'{name}' already exists – overwriting is not allowed. "
                                "Choose another name.")
            work = tmp_dir / f"up-{time.monotonic_ns()}"
            work.mkdir(parents=True, exist_ok=True)
            try:
                path = work / name
                path.write_bytes(data)
                with open(path, "rb") as fh:
                    folder.upload(fh)
            finally:
                for f in work.glob("*"):
                    f.unlink()
                work.rmdir()
            self._invalidate()
            hit = None
            for _ in range(5):  # iCloud needs a moment until the file is listed
                hit = self._find(folder, name, refresh=True)
                if hit is not None:
                    break
                time.sleep(1)
            return hit

    def move(self, node: Any, dest_folder: Any, new_name: str | None) -> Any:
        """Move and/or rename. Never overwrites."""
        with self.lock:
            node_id = node.data.get("drivewsid")
            same_folder = node.data.get("parentId") == dest_folder.data.get("drivewsid")
            target_name = self.check_name(new_name or node.name)
            existing = self._find(dest_folder, target_name, refresh=True)
            if existing is not None and existing.data.get("drivewsid") != node_id:
                raise ToolError(f"'{target_name}' already exists in the destination – "
                                "overwriting is not allowed.")
            if not same_folder:
                node.connection.move_nodes_to_node([node], dest_folder)
                moved = next((c for c in dest_folder.get_children(force=True)
                              if c.data.get("drivewsid") == node_id), None)
                if moved is None:
                    raise ToolError("Move could not be verified.")
                node = moved
            if target_name != node.name:
                node.rename(target_name)
            self._invalidate()
            result = next((c for c in dest_folder.get_children(force=True)
                           if c.data.get("drivewsid") == node_id), None)
            if result is None or result.name != target_name:
                raise ToolError("Change could not be verified – please check with list_dir.")
            return result
