"""Test des Add-ons mit nachgebautem pyicloud (kein echter Apple-Zugriff)."""
import io, json, os, sys, threading, time, types, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
D="/tmp/ictest"; os.makedirs(D, exist_ok=True)
json.dump({"apple_id":"marco@example.com","client_key":"k"*40,"max_read_mb":5}, open(f"{D}/options.json","w"))
os.environ.update(ICLOUD_OPTIONS=f"{D}/options.json", ICLOUD_DATA=D, ICLOUD_SKIP_BOOTSTRAP="1",
                  ICLOUD_PORT="8199", ICLOUD_INGRESS_PORT="8198", ICLOUD_ALLOW_ANY_INGRESS="1")

# ---- Fake pyicloud
from pypdf import PdfWriter
from PIL import Image as P
def pdf():
    w=PdfWriter(); w.add_blank_page(200,200); b=io.BytesIO(); w.write(b); return b.getvalue()
def jpg():
    b=io.BytesIO(); P.new("RGB",(4000,3000),"blue").save(b,"JPEG"); return b.getvalue()
class N:
    def __init__(s,name,kids=None,data=b""):
        s.name=name; s.kids=kids; s.data=data; s.type="folder" if kids is not None else "file"
        s.size=len(data); s.date_modified=datetime(2026,3,1,tzinfo=timezone.utc); s.date_changed=s.date_modified; s.date_last_open=None
    def get_children(s,force=False): return s.kids
    def open(s,stream=True):
        d=s.data
        class R:
            def iter_content(_,chunk_size): yield d
        return R()
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
check("8 Werkzeuge", len(rpc("tools/list")[1]["result"]["tools"])==8)
res=call("list_dir"); check("ohne Login: Hinweis", res["isError"] and "Seitenleiste" in res["content"][0]["text"])
check("UI zeigt Passwortfeld", 'name="password"' in ui(""))
check("falsches Passwort", "falsch" in ui("login",{"password":"nein"}))
check("2FA-Feld erscheint", 'name="code"' in ui("login",{"password":"richtig"}))
check("falscher Code", "ungültig" in ui("verify",{"code":"000000"}))
check("richtiger Code → verbunden", "Angemeldet" in ui("verify",{"code":"123 456"}))
server.CLOUD._checked=0
check("UI zeigt verbunden", "Verbunden mit marco@example.com" in ui(""))
res=call("list_dir"); d=res["structuredContent"]; check("list_dir Wurzel", [e["name"] for e in d["entries"]]==["Dokumente","Groß.bin"])
res=call("list_dir",path="dokumente"); check("Groß/klein egal", res["structuredContent"]["count"]==2)
res=call("search",query="*.pdf"); check("Glob-Suche", res["structuredContent"]["results"][0]["path"]=="Dokumente/Steuer/Bescheid 2025.pdf")
res=call("read_text",path="Dokumente/Steuer/Notiz.txt"); check("Text mit Umlaut", res["content"][0]["text"]=="Grüße")
res=call("read_text",path="iCloud Drive/Dokumente/Steuer/Bescheid 2025.pdf"); check("PDF + Scan-Hinweis", "Scan" in res["content"][0]["text"])
res=call("render_pdf_page",path="Dokumente/Steuer/Bescheid 2025.pdf"); check("PDF-Seite als Bild", res["content"][1]["mimeType"]=="image/jpeg")
res=call("read_image",path="Dokumente/Urlaub.jpg"); check("Bild verkleinert", res["content"][0]["type"]=="image")
res=call("read_bytes",path="Dokumente/Steuer/Notiz.txt"); check("read_bytes", res["content"][0]["text"].startswith("ICLOUD-B64"))
res=call("read_text",path="Groß.bin"); check("Größenlimit", res["isError"] and "Limit" in res["content"][0]["text"])
res=call("read_text",path="../x"); check("'..' gesperrt", res["isError"])
res=call("read_text",path="Dokumente/fehlt.pdf"); check("fehlende Datei", res["isError"] and "gibt es nicht" in res["content"][0]["text"])
res=call("status"); check("status", res["structuredContent"]["authenticated"] is True)
check("Abmelden", "Abgemeldet" in ui("logout",{}))
print("ALLES OK" if ok else "FEHLER")
