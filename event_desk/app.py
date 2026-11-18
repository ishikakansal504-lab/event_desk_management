"""Event Desk: one site for many events. Run with:  python app.py"""
import csv
import io
import os
from datetime import date, datetime

from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

import exports
import merge as M
import services as S
from models import Event, db

BASE = os.path.dirname(os.path.abspath(__file__))


def create_app(database_url=None):
    app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")
    url = database_url or os.environ.get("DATABASE_URL")

    if not url:
       if os.environ.get("RENDER"):
          raise RuntimeError("DATABASE_URL must be configured on Render.")
       url = "sqlite:///" + os.path.join(BASE, "eventdesk.db")

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = url
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 280}
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    db.init_app(app)
    with app.app_context():
        db.create_all()

    password = os.environ.get("APP_PASSWORD", "")

    if os.environ.get("RENDER") and not password:
        raise RuntimeError("APP_PASSWORD must be configured on Render.")

    @app.before_request
    def gate():
        if not password:
           return None

        a = request.authorization
        if a and a.password == password:
           return None

        return Response(
            "Password needed",
            401,
            {"WWW-Authenticate": 'Basic realm="Event Desk"'}
        )

    @app.errorhandler(Exception)
    def oops(e):
        db.session.rollback()
        code = e.code if isinstance(e, HTTPException) else 500
        if request.path.startswith("/api/"):
            msg = e.description if isinstance(e, HTTPException) else "%s: %s" % (type(e).__name__, e)
            if code == 500:
                app.logger.exception(e)
            return jsonify({"error": msg}), code
        return e if isinstance(e, HTTPException) else Response("Server error", 500)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    def body():
        return request.get_json(silent=True) or {}

    def need_event(eid):
        ev = db.session.get(Event, eid)
        if not ev:
            raise_404("Event not found")
        return ev

    def raise_404(msg):
        from werkzeug.exceptions import NotFound
        raise NotFound(msg)

    # ---------------------------------------------------------- events
    @app.get("/api/events")
    def events():
        return jsonify(S.events_overview())

    @app.get("/api/summary")
    def summary():
        return jsonify(S.summary())

    @app.post("/api/events")
    def events_create():
        name = (body().get("name") or "").strip()
        if not name:
            return jsonify({"error": "Give the event a name."}), 400
        ev = Event(name=name[:200])
        db.session.add(ev)
        db.session.commit()
        return jsonify({"id": ev.id, "name": ev.name})

    @app.get("/api/events/<int:eid>")
    def events_get(eid):
        return jsonify(S.event_detail(need_event(eid)))

    @app.patch("/api/events/<int:eid>")
    def events_rename(eid):
        ev = need_event(eid)
        name = (body().get("name") or "").strip()
        if not name:
            return jsonify({"error": "Give the event a name."}), 400
        ev.name = name[:200]
        db.session.commit()
        return jsonify({"ok": True})

    @app.delete("/api/events/<int:eid>")
    def events_delete(eid):
        need_event(eid)
        S.delete_event(eid)
        return jsonify({"ok": True})

    @app.delete("/api/events/<int:eid>/uploads/<int:uid>")
    def upload_delete(eid, uid):
        need_event(eid)
        if not S.remove_upload(eid, uid):
            return jsonify({"error": "File not found"}), 404
        return jsonify({"ok": True})

    # ---------------------------------------------------------- import
    @app.post("/api/parse")
    def parse():
        sheets = []
        if request.files.get("file"):
            f = request.files["file"]
            name = f.filename or "upload"
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in ("xlsx", "xlsm"):
                sheets = _read_xlsx(f.stream)
            elif ext in ("csv", "tsv", "txt"):
                sheets = [("Data", _read_delimited(f.read()))]
            elif ext == "xls":
                return jsonify({"error": "Old .xls files are not supported. Open it in Excel, Save As .xlsx, and upload that."}), 400
            else:
                return jsonify({"error": "Upload an .xlsx or .csv file."}), 400
        else:
            text = body().get("text") or ""
            name = "Pasted rows"
            sheets = [("Pasted", _read_delimited(text.encode("utf-8")))]
        out = []
        for sname, rows2d in sheets:
            headers, rows = M.prepare_table(rows2d)
            if headers and rows:
                out.append({"name": sname, "headers": headers, "rows": rows, "map": M.detect_roles(headers), "count": len(rows)})
        if not out:
            return jsonify({"error": "No rows found. The file needs a header row and at least one data row."}), 400
        return jsonify({"file_name": name, "sheets": out})

    @app.post("/api/import/analyze")
    def import_analyze():
        b = body()
        res = S.analyze(b["headers"], b["rows"], b.get("map") or {}, b.get("event_id"), b.get("file_name") or "upload",
                        bool(b.get("skip_cross")))
        return jsonify(res)

    @app.post("/api/import/commit")
    def import_commit():
        b = body()
        if not b.get("event_id") and not (b.get("new_name") or "").strip():
            return jsonify({"error": "Pick an event or name a new one."}), 400
        res = S.commit_import(b.get("event_id"), b.get("new_name") or "", (b.get("file_name") or "upload"),
                              b["headers"], b["rows"], b.get("map") or {}, b.get("mode") or "all", b.get("replace_upload_id"))
        return jsonify(res)

    # ---------------------------------------------------------- people
    @app.get("/api/people")
    def people():
        ev = request.args.get("event", "all")
        eid = None if ev in ("", "all") else int(ev)
        return jsonify(S.list_people(eid, request.args.get("q", ""), request.args.get("status", "all")))

    @app.get("/api/people/<int:pid>")
    def person(pid):
        d = S.person_detail(pid)
        if not d:
            return jsonify({"error": "Person not found"}), 404
        return jsonify(d)

    @app.post("/api/people")
    def people_add():
        b = body()
        ids = [int(x) for x in (b.get("event_ids") or [])]
        vals = b.get("values") or {}
        if not ids:
            return jsonify({"error": "Tick at least one event."}), 400
        if not M.norm(vals.get("name")):
            return jsonify({"error": "Enter a name."}), 400
        return jsonify({"results": S.add_person(ids, vals, b.get("extra") or {}, bool(b.get("came")))})

    # ---------------------------------------------------------- attendance and turns
    @app.post("/api/events/<int:eid>/attendance")
    def attendance(eid):
        need_event(eid)
        b = body()
        ok = S.set_came(eid, int(b["person_id"]), bool(b.get("came")))
        if not ok:
            return jsonify({"error": "That person is not in this event."}), 400
        return jsonify({"ok": True})

    @app.get("/api/events/<int:eid>/turns")
    def turns(eid):
        d = S.turn_list(eid)
        if d is None:
            return jsonify({"error": "Event not found"}), 404
        return jsonify(d)

    @app.post("/api/events/<int:eid>/turns/move")
    def turns_move(eid):
        need_event(eid)
        b = body()
        if not S.move_turn(eid, int(b["person_id"]), int(b["to"])):
            return jsonify({"error": "That person has not been ticked as came."}), 400
        return jsonify({"ok": True})

    # ---------------------------------------------------------- downloads
    def _export_data():
        ev = request.args.get("event", "all")
        q, status = request.args.get("q", ""), request.args.get("status", "all")
        if ev in ("", "all"):
            rows = S.list_people(None, q, status)
            return None, [], rows
        e = need_event(int(ev))
        rows = S.list_people(e.id, q, status)
        cols = [c for c in request.args.getlist("cols") if c in S.jl(e.cols, [])] or S.jl(e.cols, [])
        return e, cols, rows

    def _fname(base, ext):
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "" for ch in base).strip().replace(" ", "-") or "event"
        return "%s-%s.%s" % (safe, date.today().isoformat(), ext)

    @app.get("/api/export.xlsx")
    def export_xlsx():
        e, cols, rows = _export_data()
        data = exports.build_xlsx(e.name if e else "All events", cols, rows, all_events=e is None)
        return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="%s"' % _fname(e.name if e else "all-events", "xlsx")})

    @app.get("/api/export.pdf")
    def export_pdf():
        e, cols, rows = _export_data()
        view = request.args.get("view", "table")
        status = request.args.get("status", "all")
        label = {"all": "Everyone", "came": "Came", "wait": "Not yet", "merged": "Merged repeats"}.get(status, "Everyone")
        title = e.name if e else "All events"
        came = sum(1 for r in rows if r["came"])
        sub = "%d people · %d came · %d not yet · made %s" % (len(rows), came, len(rows) - came, datetime.now().strftime("%d %b %Y %H:%M"))
        if request.args.get("q"):
            sub += " · search: " + request.args["q"]
        if e is None:
            h, b = exports._all_table(rows)
            sections = [("%s (%d)" % (label, len(rows)), h, b)]
        else:
            sections = exports.pdf_sections(cols, rows, view, label)
        data = exports.build_pdf(title, sub, sections)
        return Response(data, mimetype="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="%s"' % _fname(title, "pdf")})

    return app


# ---------------------------------------------------------------- file readers

def _cell(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _read_xlsx(stream):
    from openpyxl import load_workbook
    wb = load_workbook(stream, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = [[_cell(c) for c in r] for r in ws.iter_rows(values_only=True)]
        out.append((ws.title, rows))
    return out


def _read_delimited(raw):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    first = text.split("\n", 1)[0]
    counts = {d: first.count(d) for d in ("\t", ",", ";")}
    delim = max(counts, key=counts.get) if max(counts.values()) else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in row)]


app = create_app()

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print("Event Desk running at http://%s:%d" % (host, port))
    app.run(host=host, port=port, debug=os.environ.get("DEBUG") == "1")
