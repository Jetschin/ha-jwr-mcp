"""End-to-end test of the Hue MCP app against a fake Hue Bridge (no real bridge needed).

Run: python3 tests/test_hue_addon.py
"""
import json, os, shutil, sys, threading, time, uuid, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

D = "/tmp/huetest"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
json.dump({"bridge_host": "127.0.0.1:8297", "language": "de", "allow_delete": True,
           "client_key": "k" * 40}, open(f"{D}/options.json", "w"))
os.environ.update(HUE_OPTIONS=f"{D}/options.json", HUE_DATA=D, HUE_SKIP_BOOTSTRAP="1",
                  HUE_PORT="8299", HUE_SCHEME="http", HUE_NO_AUTOPAIR="1")

# ------------------------------------------------------------ fake bridge
def rid(): return str(uuid.uuid4())
R = {k: {} for k in ("device", "light", "room", "zone", "scene", "zigbee_connectivity", "bridge",
                     "zigbee_device_discovery", "grouped_light")}
LINK = {"pressed": False}; KEY = "appkey123"; CALLS = []
def add(rtype, obj): obj.setdefault("id", rid()); obj["type"] = rtype; R[rtype][obj["id"]] = obj; return obj
br = add("bridge", {"bridge_id": "001788fffe710332"})
add("device", {"metadata": {"name": "Hue Bridge"}, "services": [{"rid": br["id"], "rtype": "bridge"}]})
add("zigbee_device_discovery", {})
def lamp(name):
    d = add("device", {"metadata": {"name": name, "archetype": "sultan_bulb"},
                       "product_data": {"product_name": "Hue color lamp", "model_id": "LCA001",
                                        "manufacturer_name": "Signify"}, "services": []})
    li = add("light", {"owner": {"rid": d["id"], "rtype": "device"}, "metadata": {"name": name},
                       "on": {"on": True}, "dimming": {"brightness": 60.0}, "color_mode": "color_temperature",
                       "color_temperature": {"mirek": 366}})
    zc = add("zigbee_connectivity", {"owner": {"rid": d["id"], "rtype": "device"}, "status": "connected"})
    d["services"] += [{"rid": li["id"], "rtype": "light"}, {"rid": zc["id"], "rtype": "zigbee_connectivity"}]
    return d
a, b, c = lamp("Bad Decke"), lamp("Büro Spot"), lamp("Neue Lampe 1")
def room(name, arch, devs):
    return add("room", {"metadata": {"name": name, "archetype": arch},
                        "children": [{"rid": x["id"], "rtype": "device"} for x in devs],
                        "services": [{"rid": rid(), "rtype": "grouped_light"}]})
bad = room("Badezimmer", "bathroom", [a]); buero = room("Büro", "office", [b])
add("scene", {"metadata": {"name": "Entspannen"}, "group": {"rid": bad["id"], "rtype": "room"},
              "actions": [{"target": {"rid": a["services"][0]["rid"], "rtype": "light"}, "action": {}}],
              "status": {"active": "inactive"}})

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def _body(self):
        n = int(self.headers.get("Content-Length") or 0); return json.loads(self.rfile.read(n)) if n else None
    def _v2(self, method):
        CALLS.append((method, self.path))
        if self.headers.get("hue-application-key") != KEY:
            return self._send(403, {"errors": [{"description": "unauthorized user"}]})
        parts = self.path.split("/")[3:]  # clip v2 resource ...
        rtype = parts[1]; oid = parts[2] if len(parts) > 2 else None
        if rtype not in R: return self._send(404, {"errors": [{"description": "not found"}], "data": []})
        if method == "GET":
            if oid:
                return self._send(200 if oid in R[rtype] else 404, {"errors": [], "data": [R[rtype][oid]] if oid in R[rtype] else []})
            return self._send(200, {"errors": [], "data": list(R[rtype].values())})
        body = self._body() or {}
        if method == "POST":
            if rtype == "room":
                for ch in body.get("children", []):
                    if any(ch["rid"] in [x["rid"] for x in r["children"]] for r in R["room"].values()):
                        return self._send(400, {"errors": [{"description": "device already in a room"}], "data": []})
            o = add(rtype, dict(body)); o.setdefault("services", [])
            return self._send(200, {"errors": [], "data": [{"rid": o["id"], "rtype": rtype}]})
        if oid not in R[rtype]: return self._send(404, {"errors": [{"description": "not found"}], "data": []})
        if method == "DELETE":
            del R[rtype][oid]; return self._send(200, {"errors": [], "data": [{"rid": oid, "rtype": rtype}]})
        if rtype == "room" and "children" in body:
            for ch in body["children"]:
                if any(ch["rid"] in [x["rid"] for x in r["children"]] for k, r in R["room"].items() if k != oid):
                    return self._send(400, {"errors": [{"description": "device already in a room"}], "data": []})
        o = R[rtype][oid]
        for k, v in body.items():
            if k == "metadata": o.setdefault("metadata", {}).update(v)
            elif k in ("identify", "recall", "action"): o["_last_" + k] = v
            else: o[k] = v
        return self._send(200, {"errors": [], "data": [{"rid": oid, "rtype": rtype}]})
    def do_GET(self):
        if self.path == "/api/0/config": return self._send(200, {"name": "Philips Hue", "modelid": "BSB002", "swversion": "1972004020"})
        self._v2("GET")
    def do_PUT(self): self._v2("PUT")
    def do_DELETE(self): self._v2("DELETE")
    def do_POST(self):
        if self.path == "/api":
            self._body()
            if not LINK["pressed"]: return self._send(200, [{"error": {"type": 101, "description": "link button not pressed"}}])
            return self._send(200, [{"success": {"username": KEY, "clientkey": "X"}}])
        self._v2("POST")

srv = ThreadingHTTPServer(("127.0.0.1", 8297), H); threading.Thread(target=srv.serve_forever, daemon=True).start()

# ------------------------------------------------------------ app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hue_mcp", "app"))
import asyncio, server  # noqa: E402
threading.Thread(target=lambda: asyncio.run(server._run()), daemon=True).start(); time.sleep(1.5)
TOKEN = json.load(open(f"{D}/secrets.json"))["token"]
n = 0
def rpc(method, params=None, token=TOKEN):
    global n; n += 1
    req = urllib.request.Request("http://127.0.0.1:8299/mcp", method="POST",
        data=json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        return {"http": e.code}
def call(_tool, **args):
    r = rpc("tools/call", {"name": _tool, "arguments": args})["result"]
    return r, (r.get("structuredContent") if not r["isError"] else r["content"][0]["text"])
ok = 0
def check(cond, label):
    global ok
    if not cond: print("FAIL:", label); sys.exit(1)
    ok += 1; print("ok  ", label)

check(rpc("ping", token="wrong") == {"http": 401}, "wrong token rejected")
init = rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]
check(init["serverInfo"]["name"] == "hue-bridge", "initialize")
names = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
check({"pair", "move_device", "delete_device", "create_scene"} <= set(names), "tools listed")
r, v = call("list_devices"); check(r["isError"] and "pair" in v, "not paired → hint")
r, v = call("pair"); check(r["isError"] and "button" in v, "pair without button")
LINK["pressed"] = True
r, v = call("pair"); check(v["paired"] and v["bridge_id"] == "001788fffe710332", "pair ok")
check(json.load(open(f"{D}/hue.json"))["app_key"] == KEY, "app key stored")
r, v = call("status"); check(v["counts"] == {"devices": 3, "lights": 3, "rooms": 2, "zones": 0}, "status counts")
r, v = call("list_devices"); check(v["count"] == 3 and all(d["name"] != "Hue Bridge" for d in v["devices"]), "bridge hidden")
r, v = call("list_devices", kind="unassigned"); check([d["name"] for d in v["devices"]] == ["Neue Lampe 1"], "unassigned filter")
r, v = call("list_devices", room="Büro"); check([d["name"] for d in v["devices"]] == ["Büro Spot"], "room filter by name")
r, v = call("rename_device", device="Neue Lampe 1", name="Bad Spiegel")
check(v["new_name"] == "Bad Spiegel" and R["device"][c["id"]]["metadata"]["name"] == "Bad Spiegel", "rename")
r, v = call("rename_device", device=c["id"], name="x" * 33); check(r["isError"], "name length checked")
r, v = call("move_device", device="Bad Spiegel", room="Badezimmer")
check(v["to_room"] == "Badezimmer" and v["from_room"] is None, "move unassigned → room")
r, v = call("move_device", device="Bad Decke", room="Büro")
check(v["from_room"] == "Badezimmer" and len(R["room"][buero["id"]]["children"]) == 2
      and len(R["room"][bad["id"]]["children"]) == 1, "move between rooms (old room first)")
r, v = call("create_group", kind="room", name="Flur", archetype="hallway", members=["Bad Decke"])
check(v["members"] == 1 and len(R["room"][buero["id"]]["children"]) == 1, "create room takes device from old room")
r, v = call("create_group", kind="zone", name="Abends", members=["Bad Decke", "Büro Spot"])
z = v["id"]; check(len(R["zone"][z]["children"]) == 2 and R["zone"][z]["children"][0]["rtype"] == "light", "zone with lights")
r, v = call("update_group", group="Abends", name="Abendlicht", remove=["Büro Spot"])
check(R["zone"][z]["metadata"]["name"] == "Abendlicht" and len(R["zone"][z]["children"]) == 1, "update zone")
r, v = call("list_groups"); check(v["count"] == 4 and any(g["name"] == "Flur" for g in v["groups"]), "list groups")
r, v = call("list_devices", query="Bad Decke"); check(v["devices"][0]["zones"][0]["name"] == "Abendlicht", "device shows zones")
r, v = call("create_scene", group="Flur", name="Hell")
sid = v["scene_id"]; act = R["scene"][sid]["actions"][0]["action"]
check(act["dimming"]["brightness"] == 60.0 and act["color_temperature"]["mirek"] == 366, "scene from current state")
r, v = call("list_scenes", group="Badezimmer"); check([s["name"] for s in v["scenes"]] == ["Entspannen"], "list scenes")
r, v = call("activate_scene", scene="Hell"); check(R["scene"][sid]["_last_recall"] == {"action": "active"}, "activate scene")
r, v = call("identify", device="Büro Spot"); check(R["device"][b["id"]]["_last_identify"]["action"] == "identify", "identify")
r, v = call("search_new_devices"); check(v["ok"], "search new devices")
r, v = call("delete_device", device="Büro Spot"); check(r["isError"] and "confirm" in v, "delete needs confirm")
r, v = call("delete_device", device="Büro Spot", confirm=True); check(b["id"] not in R["device"], "delete device")
r, v = call("delete_group", group="Abendlicht", confirm=True); check(z not in R["zone"], "delete zone")
r, v = call("api_request", method="GET", path="/clip/v2/resource/bridge"); check(v["data"][0]["bridge_id"], "raw GET")
r, v = call("api_request", method="GET", path="../api/config"); check(r["isError"], "raw path restricted")
r, v = call("rename_device", device="gibtsnicht", name="x"); check(r["isError"] and "not found" in v, "unknown device")
audit = open(f"{D}/audit.log").read(); check("delete_device" in audit and "move_device" in audit, "audit log")
print(f"\nAll {ok} checks passed.")
