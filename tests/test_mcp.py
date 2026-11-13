import base64, json, sys, urllib.request, hashlib, os

TOKEN = json.load(open("/tmp/jt/data/secrets.json"))["token"]
URL = "http://127.0.0.1:8099/mcp"
n = 0


def rpc(method, params=None, token=TOKEN, raw=None):
    global n
    n += 1
    body = raw if raw is not None else json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r:
            d = r.read()
            return r.status, (json.loads(d) if d else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def call(name, **args):
    s, r = rpc("tools/call", {"name": name, "arguments": args})
    res = r["result"]
    txt = res["content"][0].get("text", "")
    return res["isError"], txt, res


ok = True
def check(label, cond):
    global ok
    print(("OK  " if cond else "FAIL"), label)
    ok &= bool(cond)

s, r = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
check("initialize", s == 200 and r["result"]["protocolVersion"] == "2025-06-18")
s, r = rpc("x", raw=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode())
check("notification 202", s == 202)
s, r = rpc("tools/list", token="falsch")
check("falsches Token 401", s == 401)
s, r = rpc("tools/list")
names = [t["name"] for t in r["result"]["tools"]]
check("tools/list ohne delete", "list_dir" in names and not any("delete" in x or "remove" in x for x in names))
print("   ", names)

e, t, _ = call("list_dir", path="Bestand", recursive=True)
check("list_dir", not e and "Rechnung Müller.pdf" in t)
e, t, _ = call("list_dir", path="../")
check("Ausbruch .. blockiert", e and "außerhalb" in t)
e, t, _ = call("read_text", path="/etc/passwd")
check("absoluter Fremdpfad blockiert", e)
e, t, _ = call("read_text", path="Bestand/link_raus/geheim.txt")
check("Symlink-Ausbruch blockiert", e and "außerhalb" in t)
e, t, _ = call("read_text", path="/Volumes/mycloud/JWR Immobilien GbR/Bestand/00_Eingang/Rechnung Müller.pdf")
check("Mac-Pfad-Alias + pdftotext", not e and "4711" in t)
e, t, res = call("render_pdf_page", path="Bestand/00_Eingang/Rechnung Müller.pdf", page=2)
check("render_pdf_page Bild", not e and res["content"][1]["type"] == "image" and "Seite 2 von 2" in t)
import unicodedata
e, t, _ = call("file_info", path=unicodedata.normalize("NFD", "Bestand/00_Eingang/Rechnung Müller.pdf"))
check("Umlaut in anderer Unicode-Form (NFD/NFC) gefunden", not e and '"pages": 2' in t)
e, t, _ = call("file_info", path="Bestand/00_Eingang/Rechnung Müller.pdf", sha256=True)
check("file_info pages", not e and '"pages": 2' in t)

src = "/tmp/jt/root/JWR Immobilien GbR/Bestand/00_Eingang/Rechnung Müller.pdf"
orig = open(src, "rb").read()
parts, off = [], 0
while True:
    e, t, _ = call("read_bytes", path="Bestand/00_Eingang/Rechnung Müller.pdf", offset=off, length=500)
    head, b64 = t.split("\n", 1)
    h = json.loads(head[len("JWR-B64 "):])
    parts.append(base64.b64decode(b64))
    if h["eof"]:
        break
    off = h["next_offset"]
check(f"read_bytes in {len(parts)} Teilen identisch", b"".join(parts) == orig)

e, t, _ = call("write_file", path="Bestand/Test/notiz.txt", content="Hallo")
check("write_file neu (mit Ordner)", not e)
e, t, _ = call("write_file", path="Bestand/Test/notiz.txt", content="Überschreiben")
check("Überschreiben verweigert", e and "Überschreiben" in t)
e, t, _ = call("write_file", path="Bestand/Test/notiz.txt", content="x", append=True)
check("append ohne .part verweigert", e)
b = base64.b64encode(orig).decode()
call("write_file", path="Bestand/Test/kopie.pdf.part", content=b[:400], encoding="base64", append=True)
call("write_file", path="Bestand/Test/kopie.pdf.part", content=b[400:], encoding="base64", append=True)
e, t, _ = call("move", source="Bestand/Test/kopie.pdf.part", destination="Bestand/Test/kopie.pdf")
check("Upload in Teilen + move", not e and open("/tmp/jt/root/JWR Immobilien GbR/Bestand/Test/kopie.pdf", "rb").read() == orig)
e, t, _ = call("move", source="Bestand/Test/notiz.txt", destination="Bestand/Test/kopie.pdf")
check("move auf vorhandene Datei verweigert", e)
e, t, _ = call("copy", source="Bestand/00_Eingang/Rechnung Müller.pdf", destination="Bestand/Test/")
check("copy in Ordner", not e and os.path.exists("/tmp/jt/root/JWR Immobilien GbR/Bestand/Test/Rechnung Müller.pdf"))
e, t, _ = call("move", source="Bestand", destination="Bestand/Test/x")
check("Ordner in sich selbst verweigert", e)
e, t, _ = call("move", source="Bestand/Test/notiz.txt", destination="../notiz.txt")
check("move nach außen verweigert", e)
e, t, _ = call("write_file", path="Bestand/Test/bad:name.txt", content="x")
check("unzulässiger Name verweigert", e)
e, t, _ = call("mark_done", path="Bestand/00_Eingang/Rechnung Müller.pdf")
check("mark_done", not e and "_erledigt/Rechnung Müller.pdf" in t)
open(src, "wb").write(orig)
e, t, _ = call("mark_done", path="Bestand/00_Eingang/Rechnung Müller.pdf")
check("mark_done Namenskonflikt -> (2)", not e and "Rechnung Müller (2).pdf" in t)
e, t, _ = call("list_dir", path="Bestand/00_Eingang")
check("_erledigt ausgeblendet", not e and "_erledigt" not in t)
e, t, _ = call("search", query="*.pdf", include_done=True)
check("search", not e and "kopie.pdf" in t)
e, t, _ = call("make_dir", path="Bestand/Neu/Unter")
check("make_dir", not e)
e, t, _ = call("delete", path="Bestand/Test/notiz.txt")
check("delete unbekannt", e)
check("Außenordner unberührt", open("/tmp/jt/outside/geheim.txt").read() == "secret\n")
print("Audit-Zeilen:", sum(1 for _ in open("/tmp/jt/data/audit.log")))
print("ALLES OK" if ok else "FEHLER")
