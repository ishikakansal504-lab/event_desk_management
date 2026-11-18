import io, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
from app import app
from openpyxl import load_workbook

c = app.test_client()
H = ["Timestamp", "Full Name", "Email Address", "Mobile Number", "College Name", "Workshop"]
A = [
 ["2026-11-01 10:00:00", "Aarav Mehta", "aarav@example.com", "9000000001", "Northfield Institute", "Web Security"],
 ["2026-11-01 10:05:00", "Diya Nair", "diya@example.com", "9000000002", "Lakeview College", "Data"],
 ["2026-11-01 11:00:00", "Aarav Mehta", "AARAV@example.com", "+91 90000 00001", "Northfield Institute", "Data"],
 ["2026-11-01 11:01:00", "Diya Nair", "diya@example.com", "9000000002", "Lakeview College", "Data"],
 ["2026-11-01 12:00:00", "Meera Joshi", "meera@example.com", "9000000003", "Hillcrest University", "Data"],
]
mp = {"time": "Timestamp", "name": "Full Name", "email": "Email Address", "phone": "Mobile Number", "college": "College Name"}
def post(url, **kw): r = c.post(url, json=kw); assert r.status_code == 200, (url, r.status_code, r.get_json()); return r.get_json()
def get(url): r = c.get(url); assert r.status_code == 200, (url, r.status_code, r.get_data()[:200]); return r.get_json()

# parse csv text (tab separated paste) and a real xlsx
txt = "\n".join("\t".join(r) for r in [H] + A)
p = post("/api/parse", text=txt); s = p["sheets"][0]
assert s["headers"] == H and s["count"] == 5 and s["map"]["email"] == "Email Address", s["map"]
from openpyxl import Workbook
wb = Workbook(); ws = wb.active; ws.append(["Form title"]); ws.append(["Name", "Phone"]); ws.append(["Zoya", 9111111111]); bio = io.BytesIO(); wb.save(bio); bio.seek(0)
r = c.post("/api/parse", data={"file": (bio, "x.xlsx")}, content_type="multipart/form-data").get_json()
assert r["sheets"][0]["headers"] == ["Name", "Phone"] and r["sheets"][0]["rows"] == [["Zoya", "9111111111"]], r

# import into a new event
r = post("/api/import/commit", new_name="Hackathon 2026", file_name="reg1.csv", headers=H, rows=A, map=mp, mode="all")
hid = r["event"]["id"]; assert (r["new_people"], r["merged"]) == (3, 2), r
ppl = get("/api/people?event=%d" % hid); assert len(ppl) == 3
aar = next(x for x in ppl if x["name"] == "Aarav Mehta"); assert aar["n"] == 2 and aar["fields"]["Workshop"] == "Data" and aar["alts"]["Workshop"] == ["Web Security"]

# same person in a second event (same email) -> one person, two events
B = [["2026-11-05 09:00:00", "Aarav M", "aarav@example.com", "9000000001", "Northfield Institute", "Quiz"],
     ["2026-11-05 09:01:00", "Kabir Rao", "kabir@example.com", "9000000004", "Lakeview College", "Quiz"]]
r = post("/api/import/commit", new_name="Quiz Night", file_name="quiz.csv", headers=H, rows=B, map=mp, mode="all"); qid = r["event"]["id"]
allp = get("/api/people?event=all"); assert len(allp) == 4, len(allp)
aar = next(x for x in allp if x["name"].startswith("Aarav")); assert sorted(t["name"] for t in aar["events"]) == ["Hackathon 2026", "Quiz Night"]
det = get("/api/people/%d" % aar["person_id"]); assert [e["name"] for e in det["events"]] == ["Hackathon 2026", "Quiz Night"] and det["events"][0]["fields"]["Workshop"]

# search across events and by event name
assert len(get("/api/people?event=all&q=quiz")) == 2 and len(get("/api/people?event=all&q=90000%2000001")) == 1

# same-file / cross-event prompts
a = post("/api/import/analyze", event_id=hid, file_name="reg1 (1).csv", headers=H, rows=A + [["2026-11-02 09:00:00", "Isha Verma", "isha@example.com", "9000000005", "Hillcrest University", "Data"]], map=mp)
assert a["kind"] == "same" and a["already"] == 5 and a["new_rows"] == 1 and a["upload"]["filename"] == "reg1.csv", a
a = post("/api/import/analyze", new_name="x", event_id=None, file_name="other.csv", headers=H, rows=A, map=mp)
assert a["kind"] == "cross" and a["event"]["name"] == "Hackathon 2026", a
assert post("/api/import/analyze", event_id=None, file_name="other.csv", headers=H, rows=A, map=mp, skip_cross=True)["kind"] is None
r = post("/api/import/commit", event_id=hid, file_name="reg1 (1).csv", headers=H, mode="new",
         rows=A + [["2026-11-02 09:00:00", "Isha Verma", "isha@example.com", "9000000005", "Hillcrest University", "Data"]], map=mp)
assert r["skipped"] == 5 and r["new_people"] == 1, r

# attendance + first-come turns + moving
ppl = {x["name"]: x["person_id"] for x in get("/api/people?event=%d" % hid)}
for nm in ["Meera Joshi", "Aarav Mehta", "Diya Nair", "Isha Verma"]: post("/api/events/%d/attendance" % hid, person_id=ppl[nm], came=True)
t = get("/api/events/%d/turns" % hid); assert [x["name"] for x in t["turns"]] == ["Meera Joshi", "Aarav Mehta", "Diya Nair", "Isha Verma"]
post("/api/events/%d/turns/move" % hid, person_id=ppl["Isha Verma"], to=1)
assert [x["name"] for x in get("/api/events/%d/turns" % hid)["turns"]] == ["Isha Verma", "Meera Joshi", "Aarav Mehta", "Diya Nair"]
post("/api/events/%d/turns/move" % hid, person_id=ppl["Isha Verma"], to=99)
assert [x["name"] for x in get("/api/events/%d/turns" % hid)["turns"]][-1] == "Isha Verma"
post("/api/events/%d/attendance" % hid, person_id=ppl["Meera Joshi"], came=False)
tt = get("/api/events/%d/turns" % hid)["turns"]; assert [x["turn"] for x in tt] == [1, 2, 3] and tt[0]["name"] == "Aarav Mehta"
post("/api/events/%d/attendance" % hid, person_id=ppl["Meera Joshi"], came=True)
assert get("/api/events/%d/turns" % hid)["turns"][-1]["name"] == "Meera Joshi"      # new arrival goes to the end
# ticked in one event does not tick in another
q = {x["name"]: x for x in get("/api/people?event=%d" % qid)}; assert not any(x["came"] for x in q.values())
allp = get("/api/people?event=all&status=came"); assert any(x["name"].startswith("Aarav") for x in allp)

# replace keeps attendance
ups = get("/api/events/%d" % hid)["uploads"]; first = ups[0]["id"]
r = post("/api/import/commit", event_id=hid, file_name="reg-final.csv", headers=H, rows=A, map=mp, mode="replace", replace_upload_id=first)
assert r["removed"] == "reg1.csv"; assert len(get("/api/events/%d/turns" % hid)["turns"]) == 4

# add one person to several events at once, already here
r = post("/api/people", event_ids=[hid, qid], values={"name": "Neha Gupta", "college": "Northfield Institute", "email": "neha@example.com", "phone": "9222222222"}, extra={"Workshop": "Data"}, came=True)
assert len(r["results"]) == 2 and not any(x["merged"] for x in r["results"])
neha = next(x for x in get("/api/people?event=all&q=neha") if x["name"] == "Neha Gupta"); assert len(neha["events"]) == 2 and all(t["came"] for t in neha["events"])
r = post("/api/people", event_ids=[hid], values={"name": "NEHA gupta", "email": "neha@example.com"}, came=False); assert r["results"][0]["merged"]
assert get("/api/events/%d/turns" % hid)["turns"][-1]["name"].lower().startswith("neha")

# status filters + stats
ev = {e["id"]: e for e in get("/api/events")}; assert ev[hid]["people"] == 5 and ev[hid]["came"] == 5 and ev[hid]["repeats"] >= 3, ev[hid]
assert all(x["merged"] for x in get("/api/people?event=%d&status=merged" % hid))

# downloads
x = c.get("/api/export.xlsx?event=%d&cols=Full Name&cols=College Name" % hid); wb = load_workbook(io.BytesIO(x.data))
assert wb.sheetnames == ["Everyone", "Came (turn order)", "Not yet"]; assert wb["Came (turn order)"]["A1"].value == "Turn" and wb["Came (turn order)"]["B1"].value == "Full Name"
x = c.get("/api/export.xlsx?event=all"); wb = load_workbook(io.BytesIO(x.data)); assert "•" in str([c.value for c in wb["People"]["E"]])
for url in ["/api/export.pdf?event=%d&view=split" % hid, "/api/export.pdf?event=%d" % hid, "/api/export.pdf?event=all"]:
    x = c.get(url); assert x.status_code == 200 and x.data[:4] == b"%PDF", url

# remove a file / delete event
ups = get("/api/events/%d" % hid)["uploads"]; assert any(u["filename"] == "Added by hand" for u in ups)
assert c.delete("/api/events/%d/uploads/%d" % (hid, ups[0]["id"])).status_code == 200
assert c.delete("/api/events/%d" % qid).status_code == 200
assert all(len(x["events"]) == 1 for x in get("/api/people?event=all"))
print("API OK")
