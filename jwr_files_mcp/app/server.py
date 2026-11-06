#!/usr/bin/env python3
"""JWR Dateien MCP – MCP-Server (Streamable HTTP, zustandslos) für einen
einzigen freigegebenen Ordner auf der MyCloud.

Grundsätze
- Zugriff ausschließlich unterhalb von ROOT (Option ``root``). Symlinks und
  ``..`` werden über realpath aufgelöst und geprüft.
- Es gibt KEIN Löschen und KEIN Überschreiben. Erledigtes wird mit
  ``mark_done`` in einen Ordner ``_erledigt`` verschoben.
- Anhängen (``append``) ist nur für Dateien mit Endung ``.part`` erlaubt
  (Upload in Teilen), danach per ``move`` auf den endgültigen Namen.
- Jeder schreibende Zugriff wird in /data/audit.log protokolliert.
"""
from __future__ import annotations

import asyncio
import base64
import fnmatch
import hashlib
import hmac
import io
import json
import logging
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from aiohttp import web

sys.path.insert(0, os.path.dirname(__file__))
import bootstrap  # noqa: E402

VERSION = "1.1.1"
SERVER_NAME = "jwr-dateien"
SUPPORTED_PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
DONE_DIR = "_erledigt"
TEXT_EXT = {".txt", ".csv", ".md", ".json", ".xml", ".html", ".htm", ".log",
            ".tsv", ".yaml", ".yml", ".ini", ".sta", ".mt940", ".camt"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp"}
BAD_CHARS = set('\\:*?"<>|') | {chr(c) for c in range(32)}

LOG = logging.getLogger("jwr_mcp")


# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------
def load_options() -> dict:
    p = Path(os.environ.get("JWR_OPTIONS", "/data/options.json"))
    opts = json.loads(p.read_text()) if p.exists() else {}
    return {
        "root": opts.get("root", "/media/WDMycloud/JWR Immobilien GbR"),
        "external_url": (opts.get("external_url") or "").rstrip("/"),
        "max_read_mb": int(opts.get("max_read_mb", 25)),
        "rotate_secret": bool(opts.get("rotate_secret", False)),
        "client_key": opts.get("client_key", ""),
        "log_level": opts.get("log_level", "info"),
        "port": int(os.environ.get("JWR_PORT", "8099")),
    }


OPTS = load_options()
ROOT = os.path.realpath(OPTS["root"])
DATA_DIR = Path(os.environ.get("JWR_DATA", "/data"))
AUDIT = DATA_DIR / "audit.log"
MAX_READ = OPTS["max_read_mb"] * 1024 * 1024


class ToolError(Exception):
    pass


# --------------------------------------------------------------------------
# Pfadprüfung
# --------------------------------------------------------------------------
ALIASES = [
    "/Volumes/mycloud/JWR Immobilien GbR",
    "/media/WDMycloud/JWR Immobilien GbR",
    "JWR Immobilien GbR",
]


def root_available() -> None:
    if not os.path.isdir(ROOT):
        raise ToolError(
            f"Der freigegebene Ordner ist nicht erreichbar ({ROOT}). "
            "Ist die MyCloud eingeschaltet und in Home Assistant eingebunden?")


def resolve(rel: str | None, must_exist: bool = True) -> str:
    """Pfad (relativ zum Wurzelordner) sicher auflösen."""
    root_available()
    rel = (rel or "").strip().replace("\\", "/")
    if "\x00" in rel:
        raise ToolError("Ungültiger Pfad.")
    for a in ALIASES:
        if rel == a or rel.startswith(a + "/"):
            rel = rel[len(a):]
            break
    rel = rel.lstrip("/")
    full = os.path.realpath(os.path.join(ROOT, rel))
    if os.path.commonpath([full, ROOT]) != ROOT:
        raise ToolError("Zugriff verweigert: Pfad liegt außerhalb des freigegebenen Ordners.")
    if must_exist and not os.path.exists(full):
        raise ToolError(f"Nicht gefunden: {display(full)}")
    return full


def display(full: str) -> str:
    r = os.path.relpath(full, ROOT)
    return "" if r == "." else r


def check_name(full: str) -> None:
    name = os.path.basename(full)
    if not name or name in (".", ".."):
        raise ToolError("Ungültiger Dateiname.")
    if any(c in BAD_CHARS for c in name):
        raise ToolError(f"Dateiname enthält unzulässige Zeichen: {name!r}")
    if name.endswith((" ", ".")):
        raise ToolError("Dateiname darf nicht mit Leerzeichen oder Punkt enden.")
    if len(name.encode()) > 255:
        raise ToolError("Dateiname zu lang.")


def audit(action: str, **kw) -> None:
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "action": action, **kw}
    LOG.info("AUDIT %s", json.dumps(entry, ensure_ascii=False))
    try:
        with AUDIT.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def unique_target(full: str) -> str:
    if not os.path.exists(full):
        return full
    base, ext = os.path.splitext(full)
    for i in range(2, 1000):
        cand = f"{base} ({i}){ext}"
        if not os.path.exists(cand):
            return cand
    raise ToolError("Kein freier Zielname gefunden.")


def entry_info(full: str) -> dict:
    st = os.stat(full)
    is_dir = os.path.isdir(full)
    d = {
        "path": display(full),
        "name": os.path.basename(full),
        "type": "dir" if is_dir else "file",
        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }
    if not is_dir:
        d["size"] = st.st_size
    return d


def run(cmd: list[str], timeout: int = 120) -> bytes:
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"Zeitüberschreitung bei {cmd[0]}") from e
    if res.returncode != 0:
        raise ToolError(f"{cmd[0]} fehlgeschlagen: {res.stderr.decode(errors='replace')[:400]}")
    return res.stdout


def pdf_pages(full: str) -> int | None:
    try:
        out = run(["pdfinfo", full], timeout=30).decode(errors="replace")
    except ToolError:
        return None
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    return None


# --------------------------------------------------------------------------
# Werkzeuge
# --------------------------------------------------------------------------
def t_list_dir(path: str = "", recursive: bool = False, max_depth: int = 3,
               pattern: str | None = None, include_done: bool = False,
               max_entries: int = 500) -> dict:
    base = resolve(path)
    if not os.path.isdir(base):
        raise ToolError("Kein Ordner.")
    max_entries = max(1, min(int(max_entries), 5000))
    out, truncated = [], False
    base_depth = base.rstrip("/").count("/")
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and (include_done or d != DONE_DIR))
        depth = dirpath.rstrip("/").count("/") - base_depth
        items = [(d, True) for d in dirnames] + [(f, False) for f in sorted(filenames)
                                                  if not f.startswith(".")]
        for name, _ in items:
            if pattern and not fnmatch.fnmatch(name.lower(), pattern.lower()):
                continue
            out.append(entry_info(os.path.join(dirpath, name)))
            if len(out) >= max_entries:
                truncated = True
                break
        if truncated:
            break
        if not recursive or depth + 1 >= int(max_depth):
            dirnames[:] = []
    return {"folder": display(base), "entries": out, "truncated": truncated}


def t_search(query: str, path: str = "", max_results: int = 200,
             include_done: bool = False) -> dict:
    base = resolve(path)
    q = (query or "").lower()
    if not q:
        raise ToolError("Suchbegriff fehlt.")
    hits = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and (include_done or d != DONE_DIR)]
        for name in dirnames + filenames:
            if q in name.lower() or fnmatch.fnmatch(name.lower(), q):
                hits.append(entry_info(os.path.join(dirpath, name)))
                if len(hits) >= int(max_results):
                    return {"results": hits, "truncated": True}
    return {"results": hits, "truncated": False}


def t_file_info(path: str, sha256: bool = False) -> dict:
    full = resolve(path)
    d = entry_info(full)
    if d["type"] == "file":
        d["mime"] = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.lower().endswith(".pdf"):
            d["pages"] = pdf_pages(full)
        if sha256:
            h = hashlib.sha256()
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            d["sha256"] = h.hexdigest()
    return d


def t_read_text(path: str, first_page: int | None = None, last_page: int | None = None,
                max_chars: int = 60000, layout: bool = True) -> dict:
    full = resolve(path)
    if os.path.isdir(full):
        raise ToolError("Das ist ein Ordner.")
    ext = os.path.splitext(full)[1].lower()
    max_chars = max(1000, min(int(max_chars), 400000))
    info = {"path": display(full), "size": os.path.getsize(full)}
    if ext == ".pdf":
        cmd = ["pdftotext", "-enc", "UTF-8"]
        if layout:
            cmd.append("-layout")
        if first_page:
            cmd += ["-f", str(int(first_page))]
        if last_page:
            cmd += ["-l", str(int(last_page))]
        cmd += [full, "-"]
        text = run(cmd).decode("utf-8", errors="replace")
        info["pages"] = pdf_pages(full)
        if len(text.strip()) < 20:
            info["hinweis"] = ("Keine Textebene gefunden (Scan). Seiten mit "
                               "render_pdf_page als Bild ansehen.")
    elif ext in TEXT_EXT or os.path.getsize(full) < 2_000_000 and ext not in IMAGE_EXT:
        raw = open(full, "rb").read(max_chars * 4)
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                info["encoding"] = enc
                break
            except UnicodeDecodeError:
                continue
    else:
        raise ToolError("Für diesen Dateityp gibt es keinen Text. Bilder mit read_image, "
                        "Rohdaten mit read_bytes lesen.")
    info["truncated"] = len(text) > max_chars
    info["text"] = text[:max_chars]
    return info


def _image_block(png: bytes, mime: str = "image/png") -> dict:
    return {"type": "image", "data": base64.b64encode(png).decode(), "mimeType": mime}


def _shrink(data: bytes, max_px: int, quality: int = 80) -> tuple[bytes, str]:
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    img.thumbnail((max_px, max_px))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue(), "image/jpeg"


def t_render_pdf_page(path: str, page: int = 1, dpi: int = 110, max_px: int = 1600):
    full = resolve(path)
    if not full.lower().endswith(".pdf"):
        raise ToolError("Keine PDF-Datei.")
    page = max(1, int(page))
    dpi = max(40, min(int(dpi), 220))
    with tempfile.TemporaryDirectory() as td:
        run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png",
             "-singlefile", full, os.path.join(td, "p")])
        png = open(os.path.join(td, "p.png"), "rb").read()
    data, mime = _shrink(png, int(max_px))
    pages = pdf_pages(full)
    return [
        {"type": "text", "text": f"{display(full)} – Seite {page} von {pages}"},
        _image_block(data, mime),
    ]


def t_read_image(path: str, max_px: int = 1600):
    full = resolve(path)
    if os.path.splitext(full)[1].lower() not in IMAGE_EXT:
        raise ToolError("Kein unterstütztes Bildformat.")
    data, mime = _shrink(open(full, "rb").read(), int(max_px))
    return [{"type": "text", "text": display(full)}, _image_block(data, mime)]


def t_read_bytes(path: str, offset: int = 0, length: int | None = None):
    full = resolve(path)
    if os.path.isdir(full):
        raise ToolError("Das ist ein Ordner.")
    size = os.path.getsize(full)
    offset = max(0, int(offset))
    length = MAX_READ if length is None else max(1, min(int(length), MAX_READ))
    with open(full, "rb") as fh:
        fh.seek(offset)
        chunk = fh.read(length)
    end = offset + len(chunk)
    header = {
        "path": display(full), "size": size, "offset": offset, "length": len(chunk),
        "eof": end >= size, "next_offset": None if end >= size else end,
        "chunk_sha256": hashlib.sha256(chunk).hexdigest(),
        "mime": mimetypes.guess_type(full)[0] or "application/octet-stream",
    }
    # Eine einzige Textausgabe: 1. Zeile JSON-Kopf, ab 2. Zeile Base64.
    # So lässt sie sich auch aus einer gespeicherten Tool-Ausgabe einfach dekodieren.
    return [{"type": "text",
             "text": "JWR-B64 " + json.dumps(header, ensure_ascii=False) + "\n"
                     + base64.b64encode(chunk).decode()}]


def t_write_file(path: str, content: str, encoding: str = "text",
                 append: bool = False, create_dirs: bool = True) -> dict:
    full = resolve(path, must_exist=False)
    check_name(full)
    if os.path.isdir(full):
        raise ToolError("Ziel ist ein Ordner.")
    if encoding == "base64":
        try:
            data = base64.b64decode(content, validate=False)
        except Exception as e:
            raise ToolError(f"Base64 ungültig: {e}") from e
    elif encoding == "text":
        data = content.encode("utf-8")
    else:
        raise ToolError("encoding muss 'text' oder 'base64' sein.")
    parent = os.path.dirname(full)
    if not os.path.isdir(parent):
        if not create_dirs:
            raise ToolError("Zielordner existiert nicht.")
        os.makedirs(parent, exist_ok=True)
    if append:
        if not full.endswith(".part"):
            raise ToolError("Anhängen ist nur bei Dateien mit Endung .part erlaubt.")
        with open(full, "ab") as fh:
            fh.write(data)
        audit("append", path=display(full), bytes=len(data))
        return {"ok": True, "path": display(full), "size": os.path.getsize(full)}
    if os.path.exists(full):
        raise ToolError(f"Datei existiert bereits, Überschreiben ist nicht erlaubt: {display(full)}")
    tmp = os.path.join(parent, f".jwr-upload-{os.getpid()}-{time.time_ns()}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    if os.path.exists(full):  # Wettlauf
        os.unlink(tmp)
        raise ToolError("Datei existiert bereits.")
    os.rename(tmp, full)
    audit("write", path=display(full), bytes=len(data))
    return {"ok": True, "path": display(full), "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def _prepare_dst(src_full: str, destination: str, create_dirs: bool) -> str:
    dst = resolve(destination, must_exist=False)
    if os.path.isdir(dst):  # Ziel ist ein Ordner -> Name beibehalten
        dst = os.path.join(dst, os.path.basename(src_full))
    check_name(dst)
    if dst == ROOT or src_full == ROOT:
        raise ToolError("Der Wurzelordner kann nicht verschoben werden.")
    if os.path.isdir(src_full) and (dst + "/").startswith(src_full + "/"):
        raise ToolError("Ordner kann nicht in sich selbst verschoben werden.")
    if os.path.exists(dst) and not os.path.samefile(src_full, dst):
        raise ToolError(f"Ziel existiert bereits, Überschreiben ist nicht erlaubt: {display(dst)}")
    parent = os.path.dirname(dst)
    if not os.path.isdir(parent):
        if not create_dirs:
            raise ToolError("Zielordner existiert nicht.")
        os.makedirs(parent, exist_ok=True)
    return dst


def t_move(source: str, destination: str, create_dirs: bool = True) -> dict:
    src = resolve(source)
    dst = _prepare_dst(src, destination, create_dirs)
    os.rename(src, dst)
    audit("move", source=display(src), destination=display(dst))
    return {"ok": True, "source": display(src), "destination": display(dst)}


def t_copy(source: str, destination: str, create_dirs: bool = True) -> dict:
    src = resolve(source)
    if os.path.isdir(src):
        raise ToolError("Nur Dateien können kopiert werden.")
    dst = _prepare_dst(src, destination, create_dirs)
    if os.path.exists(dst):
        raise ToolError("Ziel existiert bereits.")
    tmp = os.path.join(os.path.dirname(dst), f".jwr-copy-{os.getpid()}-{time.time_ns()}.tmp")
    shutil.copyfile(src, tmp)
    try:
        shutil.copystat(src, tmp)
    except OSError:
        pass
    os.rename(tmp, dst)
    audit("copy", source=display(src), destination=display(dst))
    return {"ok": True, "source": display(src), "destination": display(dst),
            "size": os.path.getsize(dst)}


def t_make_dir(path: str) -> dict:
    full = resolve(path, must_exist=False)
    check_name(full)
    existed = os.path.isdir(full)
    os.makedirs(full, exist_ok=True)
    if not existed:
        audit("mkdir", path=display(full))
    return {"ok": True, "path": display(full), "created": not existed}


def t_mark_done(path: str) -> dict:
    src = resolve(path)
    if src == ROOT:
        raise ToolError("Der Wurzelordner kann nicht als erledigt markiert werden.")
    if DONE_DIR in Path(display(src)).parts[:-1]:
        raise ToolError("Liegt bereits in einem _erledigt-Ordner.")
    done = os.path.join(os.path.dirname(src), DONE_DIR)
    os.makedirs(done, exist_ok=True)
    dst = unique_target(os.path.join(done, os.path.basename(src)))
    os.rename(src, dst)
    audit("mark_done", source=display(src), destination=display(dst))
    return {"ok": True, "source": display(src), "destination": display(dst)}


S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}
PATH_HINT = ("Pfad relativ zum Ordner 'JWR Immobilien GbR', z. B. "
             "'Bestand/00_Eingang/rechnung.pdf'. Leer = Wurzel.")

TOOLS = {
    "list_dir": (t_list_dir, "Ordnerinhalt auflisten (Dateien mit Größe und Änderungsdatum). "
                 "_erledigt-Ordner werden standardmäßig ausgeblendet.",
                 {"path": {**S, "description": PATH_HINT}, "recursive": B, "max_depth": I,
                  "pattern": {**S, "description": "Glob-Filter, z. B. '*.pdf'"},
                  "include_done": B, "max_entries": I}, [], True),
    "search": (t_search, "Dateien/Ordner nach Namensteil oder Glob rekursiv suchen.",
               {"query": S, "path": {**S, "description": PATH_HINT}, "max_results": I,
                "include_done": B}, ["query"], True),
    "file_info": (t_file_info, "Metadaten einer Datei (Größe, Datum, MIME, PDF-Seiten, optional SHA-256).",
                  {"path": {**S, "description": PATH_HINT}, "sha256": B}, ["path"], True),
    "read_text": (t_read_text, "Text einer Datei lesen. PDFs werden per pdftotext ausgelesen "
                  "(Seitenbereich wählbar). Bei Scans ohne Textebene render_pdf_page verwenden.",
                  {"path": {**S, "description": PATH_HINT}, "first_page": I, "last_page": I,
                   "max_chars": I, "layout": B}, ["path"], True),
    "render_pdf_page": (t_render_pdf_page, "Eine PDF-Seite als Bild zurückgeben (zum Ansehen von Scans).",
                        {"path": {**S, "description": PATH_HINT}, "page": I, "dpi": I,
                         "max_px": I}, ["path"], True),
    "read_image": (t_read_image, "Bilddatei (JPG/PNG/TIFF …) verkleinert als Bild zurückgeben.",
                   {"path": {**S, "description": PATH_HINT}, "max_px": I}, ["path"], True),
    "read_bytes": (t_read_bytes, "Rohdaten einer Datei (z. B. PDF) als Base64 lesen, bei großen "
                   "Dateien in Teilen über offset/length. Ausgabe: 1. Zeile 'JWR-B64 {json-kopf}', "
                   "danach Base64. Zum lokalen Speichern: Base64 dekodieren, Teile aneinanderhängen.",
                   {"path": {**S, "description": PATH_HINT}, "offset": I, "length": I},
                   ["path"], True),
    "write_file": (t_write_file, "Neue Datei schreiben (Text oder Base64). Überschreiben ist nie "
                   "erlaubt. Große Dateien: in Teilen mit append=true an 'name.pdf.part' anhängen, "
                   "danach mit move umbenennen. Base64-Teile müssen ein Vielfaches von 4 Zeichen lang sein.",
                   {"path": {**S, "description": PATH_HINT}, "content": S,
                    "encoding": {"type": "string", "enum": ["text", "base64"]},
                    "append": B, "create_dirs": B}, ["path", "content"], False),
    "move": (t_move, "Datei oder Ordner verschieben bzw. umbenennen. Ist das Ziel ein vorhandener "
             "Ordner, wird hineinverschoben. Kein Überschreiben.",
             {"source": S, "destination": S, "create_dirs": B}, ["source", "destination"], False),
    "copy": (t_copy, "Datei kopieren (kein Überschreiben).",
             {"source": S, "destination": S, "create_dirs": B}, ["source", "destination"], False),
    "make_dir": (t_make_dir, "Ordner anlegen (inkl. Zwischenordner).",
                 {"path": {**S, "description": PATH_HINT}}, ["path"], False),
    "mark_done": (t_mark_done, "Erledigte Datei in den Unterordner '_erledigt' desselben Ordners "
                  "verschieben (Ersatz für Löschen). Bei Namensgleichheit wird ' (2)' angehängt.",
                  {"path": {**S, "description": PATH_HINT}}, ["path"], False),
}


def tool_list() -> list[dict]:
    out = []
    for name, (_, desc, props, req, ro) in TOOLS.items():
        out.append({
            "name": name,
            "description": desc,
            "inputSchema": {"type": "object", "properties": props, "required": req,
                            "additionalProperties": False},
            "annotations": {"readOnlyHint": ro, "destructiveHint": False,
                            "idempotentHint": ro, "openWorldHint": False},
        })
    return out


def call_tool(name: str, args: dict) -> dict:
    if name not in TOOLS:
        return {"content": [{"type": "text", "text": f"Unbekanntes Werkzeug: {name}"}], "isError": True}
    fn = TOOLS[name][0]
    try:
        res = fn(**(args or {}))
    except ToolError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except TypeError as e:
        return {"content": [{"type": "text", "text": f"Falsche Parameter: {e}"}], "isError": True}
    except OSError as e:
        LOG.warning("OSError in %s: %s", name, e)
        return {"content": [{"type": "text", "text": f"Dateisystemfehler: {e.strerror or e}"}],
                "isError": True}
    except Exception as e:  # noqa: BLE001
        LOG.exception("Fehler in %s", name)
        return {"content": [{"type": "text", "text": f"Interner Fehler: {e}"}], "isError": True}
    if isinstance(res, list):
        return {"content": res, "isError": False}
    return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)}],
            "structuredContent": res, "isError": False}


# --------------------------------------------------------------------------
# MCP / JSON-RPC
# --------------------------------------------------------------------------
INSTRUCTIONS = (
    "Dateizugriff auf die Ablage 'JWR Immobilien GbR' (WD MyCloud über Home Assistant). "
    "Alle Pfade sind relativ zu diesem Ordner (z. B. 'Bestand/00_Eingang'). "
    "Löschen und Überschreiben sind nicht möglich; Erledigtes mit mark_done nach '_erledigt' "
    "verschieben. PDFs: read_text für Text, render_pdf_page für Scans, read_bytes für Rohdaten."
)


def rpc_result(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def rpc_error(mid, code, msg):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


async def handle_message(msg: dict):
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return rpc_error(None, -32600, "Invalid Request")
    method, mid = msg.get("method"), msg.get("id")
    params = msg.get("params") or {}
    if method is None:  # Antwort des Clients – ignorieren
        return None
    if mid is None:  # Notification
        return None
    if method == "initialize":
        req = params.get("protocolVersion")
        ver = req if req in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return rpc_result(mid, {
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "JWR Dateien (MyCloud)", "version": VERSION},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return rpc_result(mid, {})
    if method == "tools/list":
        return rpc_result(mid, {"tools": tool_list()})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        LOG.info("tools/call %s %s", name, {k: v for k, v in args.items() if k != "content"})
        res = await asyncio.get_running_loop().run_in_executor(None, call_tool, name, args)
        return rpc_result(mid, res)
    if method in ("resources/list",):
        return rpc_result(mid, {"resources": []})
    if method in ("resources/templates/list",):
        return rpc_result(mid, {"resourceTemplates": []})
    if method in ("prompts/list",):
        return rpc_result(mid, {"prompts": []})
    return rpc_error(mid, -32601, f"Method not found: {method}")


def authorized(request: web.Request, token: str) -> bool:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return hmac.compare_digest(auth[7:].strip(), token)
    return False


async def mcp_post(request: web.Request) -> web.StreamResponse:
    if not authorized(request, request.app["token"]):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response(rpc_error(None, -32700, "Parse error"), status=400)
    if isinstance(payload, list):
        res = [r for r in [await handle_message(m) for m in payload] if r is not None]
        if not res:
            return web.Response(status=202)
        return web.json_response(res, dumps=lambda o: json.dumps(o, ensure_ascii=False))
    res = await handle_message(payload)
    if res is None:
        return web.Response(status=202)
    return web.json_response(res, dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def mcp_other(request: web.Request) -> web.Response:
    return web.Response(status=405, headers={"Allow": "POST"})


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "root_available": os.path.isdir(ROOT), "version": VERSION})


def main() -> None:
    logging.basicConfig(level=getattr(logging, OPTS["log_level"].upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secrets = bootstrap.load_secrets(DATA_DIR, rotate=OPTS["rotate_secret"])
    LOG.info("JWR Dateien MCP %s – Wurzel: %s (erreichbar: %s)", VERSION, ROOT, os.path.isdir(ROOT))
    if os.environ.get("JWR_SKIP_BOOTSTRAP") != "1":
        bootstrap.start_background(OPTS, secrets)
    app = web.Application(client_max_size=40 * 1024 * 1024)
    app["token"] = secrets["token"]
    app.router.add_post("/mcp", mcp_post)
    app.router.add_route("GET", "/mcp", mcp_other)
    app.router.add_route("DELETE", "/mcp", mcp_other)
    app.router.add_get("/health", health)
    web.run_app(app, host="0.0.0.0", port=OPTS["port"], access_log=None, print=None)


if __name__ == "__main__":
    main()
