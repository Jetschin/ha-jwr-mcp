"""End-to-end test of the app with a fake pyicloud (no real Apple access).

Run: python3 tests/test_icloud_addon.py [en|de]
"""
import io, json, os, sys, threading, time, types, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
LANG=sys.argv[1] if len(sys.argv)>1 else "en"
import shutil; D="/tmp/ictest"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
WRITE=os.environ.get("TEST_WRITE","1")=="1"
json.dump({"apple_id":"user@example.com","language":LANG,"allow_write":WRITE,"client_key":"k"*40,"max_read_mb":5}, open(f"{D}/options.json","w"))
os.environ.update(ICLOUD_OPTIONS=f"{D}/options.json", ICLOUD_DATA=D, ICLOUD_SKIP_BOOTSTRAP="1",
                  ICLOUD_PORT="8199", ICLOUD_INGRESS_PORT="8198", ICLOUD_ALLOW_ANY_INGRESS="1")

# ---- Fake pyicloud
from pypdf import PdfWriter
from PIL import Image as P
def pdf():
    w=PdfWriter(); w.add_blank_page(200,200); b=io.BytesIO(); w.write(b); return b.getvalue()
def jpg():
    b=io.BytesIO(); P.new("RGB",(4000,3000),"blue").save(b,"JPEG"); return b.getvalue()
import itertools
_ids=itertools.count(1)
class Conn:
    def move_nodes_to_node(self, nodes, dest):
        for n in nodes:
            n.parent.kids.remove(n); dest.kids.append(n); n.parent=dest; n.data["parentId"]=dest.data["drivewsid"]
class N:
    conn=Conn()
    def __init__(s,name,kids=None,data=b"",parent=None):
        s.name=name; s.kids=kids; s.blob=data; s.type="folder" if kids is not None else "file"
        s.size=len(data); s.date_modified=datetime(2026,3,1,tzinfo=timezone.utc); s.date_changed=s.date_modified; s.date_last_open=None
        s.connection=N.conn; s.parent=parent
        s.data={"drivewsid":f"ID{next(_ids)}","etag":"e","parentId":parent.data["drivewsid"] if parent else None}
        for k in kids or []:
            k.parent=s; k.data["parentId"]=s.data["drivewsid"]
    def get_children(s,force=False): return list(s.kids)
    def open(s,stream=True):
        d=s.blob
        class R:
            def iter_content(_,chunk_size): yield d
        return R()
    def mkdir(s,name): s.kids.append(N(name,[],parent=s))
    def upload(s,fh):
        s.kids.append(N(os.path.basename(fh.name),data=fh.read(),parent=s))
    def rename(s,name): s.name=name
ROOT=N("root",[N("Dokumente",[N("Steuer",[N("Bescheid 2025.pdf",data=pdf()),N("Notiz.txt",data="Grüße".encode())]),N("Urlaub.jpg",data=jpg())]),N("Groß.bin",data=b"x"*(6*1024*1024))])
class Drive:
    root=ROOT
    def refresh_root(s): pass
STATE={"auth":False}
class FakeService:
    def __init__(s, apple_id, password=None, cookie_directory=None, authenticate=True, refresh_interval=None):
        s.drive=Drive(); s.requires_2sa=False; s.is_trusted_session=False
        if password is not None:
            if password!="richtig":
                raise FakeExc.PyiCloudFailedLoginException("bad")
            s.requires_2fa=True
        else:
            s.requires_2fa=False
    def get_auth_status(s): return {"authenticated":STATE["auth"],"trusted_session":STATE["auth"]}
    def request_2fa_code(s): return True
    def validate_2fa_code(s,code): return code=="123456"
    def trust_session(s): STATE["auth"]=True; s.is_trusted_session=True; return True
FakeExc=types.ModuleType("pyicloud.exceptions")
for n in ["PyiCloudFailedLoginException","PyiCloudAccountLockedException","PyiCloudNoTrustedNumberAvailable"]:
    setattr(FakeExc,n,type(n,(Exception,),{}))
FakeExc.PyiCloudAccountLockedException=type("PyiCloudAccountLockedException",(FakeExc.PyiCloudFailedLoginException,),{})
mod=types.ModuleType("pyicloud"); mod.PyiCloudService=FakeService
sys.modules["pyicloud"]=mod; sys.modules["pyicloud.exceptions"]=FakeExc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "icloud_mcp", "app"))
import server, bootstrap
bootstrap.notify=lambda *a,**k: print("NOTIFY:",a[0]); bootstrap.dismiss_notification=lambda *a: print("DISMISS",a[0])
server.bootstrap=bootstrap
threading.Thread(target=server.main,daemon=True).start(); time.sleep(2)
TOKEN=json.load(open(f"{D}/secrets.json"))["token"]

ok=True
def check(l,c):
    global ok; print(("OK  " if c else "FAIL"),l); ok&=bool(c)
n=0
def rpc(method,params=None,token=TOKEN):
    global n; n+=1
    req=urllib.request.Request("http://127.0.0.1:8199/mcp",data=json.dumps({"jsonrpc":"2.0","id":n,"method":method,"params":params or {}}).encode(),
        headers={"Content-Type":"application/json","Authorization":f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r: return r.status,json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code,None
def call(name,**a):
    s,r=rpc("tools/call",{"name":name,"arguments":a}); return r["result"]
def ui(path,data=None):
    req=urllib.request.Request("http://127.0.0.1:8198/"+path,data=urllib.parse.urlencode(data).encode() if data is not None else None)
    with urllib.request.urlopen(req) as r: return r.read().decode()

s,r=rpc("initialize",{"protocolVersion":"2025-06-18"}); check("initialize", r["result"]["serverInfo"]["title"]=="iCloud Drive")
check("falsches Token 401", rpc("tools/list",token="x")[0]==401)
check("Werkzeuganzahl", len(rpc("tools/list")[1]["result"]["tools"])==(11 if WRITE else 8))
res=call("list_dir"); check("ohne Login: Hinweis", res["isError"] and "sidebar" in res["content"][0]["text"])
check("UI zeigt Passwortfeld", 'name="password"' in ui(""))
L=lambda en,de: en if LANG=="en" else de
check("falsches Passwort", L("Wrong","falsch") in ui("login",{"password":"nein"}))
check("2FA-Feld erscheint", 'name="code"' in ui("login",{"password":"richtig"}))
check("falscher Code", L("Invalid","ungültig") in ui("verify",{"code":"000000"}))
check("richtiger Code → verbunden", L("Signed in","Angemeldet") in ui("verify",{"code":"123 456"}))
server.CLOUD._checked=0
check("UI zeigt verbunden", L("Connected to","Verbunden mit")+" user@example.com" in ui(""))
res=call("list_dir"); d=res["structuredContent"]; check("list_dir Wurzel", [e["name"] for e in d["entries"]]==["Dokumente","Groß.bin"])
res=call("list_dir",path="dokumente"); check("Groß/klein egal", res["structuredContent"]["count"]==2)
res=call("search",query="*.pdf"); check("Glob-Suche", res["structuredContent"]["results"][0]["path"]=="Dokumente/Steuer/Bescheid 2025.pdf")
res=call("read_text",path="Dokumente/Steuer/Notiz.txt"); check("Text mit Umlaut", res["content"][0]["text"]=="Grüße")
res=call("read_text",path="iCloud Drive/Dokumente/Steuer/Bescheid 2025.pdf"); check("PDF + Scan-Hinweis", "scan" in res["content"][0]["text"])
res=call("render_pdf_page",path="Dokumente/Steuer/Bescheid 2025.pdf"); check("PDF-Seite als Bild", res["content"][1]["mimeType"]=="image/jpeg")
res=call("read_image",path="Dokumente/Urlaub.jpg"); check("Bild verkleinert", res["content"][0]["type"]=="image")
res=call("read_bytes",path="Dokumente/Steuer/Notiz.txt"); check("read_bytes", res["content"][0]["text"].startswith("ICLOUD-B64"))
res=call("read_text",path="Groß.bin"); check("Größenlimit", res["isError"] and "limit" in res["content"][0]["text"])
res=call("read_text",path="../x"); check("'..' gesperrt", res["isError"])
res=call("read_text",path="Dokumente/fehlt.pdf"); check("fehlende Datei", res["isError"] and "does not exist" in res["content"][0]["text"])
res=call("status"); check("status", res["structuredContent"]["authenticated"] is True)
if WRITE:
    import base64 as b64
    res=call("write_file",path="Dokumente/Neu/Hallo.txt",content="Hallo Welt"); check("write_file + Ordner anlegen", not res["isError"])
    res=call("read_text",path="Dokumente/Neu/Hallo.txt"); check("geschriebene Datei lesbar", res["content"][0]["text"]=="Hallo Welt")
    res=call("write_file",path="Dokumente/Neu/Hallo.txt",content="x"); check("kein Überschreiben", res["isError"] and "already exists" in res["content"][0]["text"])
    blob=bytes(range(256))*100; e=b64.b64encode(blob).decode()
    call("write_file",path="Dokumente/Neu/bin.dat",content=e[:4000],encoding="base64",chunk="start")
    call("write_file",path="Dokumente/Neu/bin.dat",content=e[4000:8000],encoding="base64",chunk="append")
    res=call("write_file",path="Dokumente/Neu/bin.dat",content=e[8000:],encoding="base64",chunk="finish")
    check("Upload in Teilen", not res["isError"] and res["structuredContent"]["size"]==len(blob))
    res=call("read_bytes",path="Dokumente/Neu/bin.dat"); check("Teile korrekt zusammengesetzt", b64.b64decode(res["content"][0]["text"].split("\n",1)[1])==blob)
    res=call("make_dir",path="Archiv/2026"); check("make_dir", not res["isError"])
    res=call("move",source="Dokumente/Neu/Hallo.txt",destination="Archiv/2026"); check("move in Ordner", not res["isError"] and res["structuredContent"]["destination"]=="Archiv/2026/Hallo.txt")
    res=call("move",source="Archiv/2026/Hallo.txt",destination="Archiv/2026/Gruss.txt"); check("umbenennen", not res["isError"] and call("file_info",path="Archiv/2026/Gruss.txt")["isError"] is False)
    res=call("move",source="Dokumente/Neu/bin.dat",destination="Archiv/2026/Gruss.txt"); check("move ohne Überschreiben", res["isError"])
    res=call("move",source="Archiv",destination="Archiv/2026/x"); check("Ordner nicht in sich selbst", res["isError"])
    check("Audit-Log", os.path.exists(f"{D}/audit.log") and "write_file" in open(f"{D}/audit.log").read())
check("Abmelden", L("Signed out","Abgemeldet") in ui("logout",{}))
print("ALL OK" if ok else "FAILED"); sys.exit(0 if ok else 1)
