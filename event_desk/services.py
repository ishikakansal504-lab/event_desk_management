"""Business logic: importing, rebuilding merged people, attendance and turn order, listing."""
import json

from sqlalchemy import func

import merge as M
from models import Attendance, Entry, Event, Person, Submission, Upload, db, now_ms

CORE = ["name", "college", "email", "phone"]
DEFAULT_MAP = {"name": "Name", "college": "College", "email": "Email", "phone": "Phone"}
MANUAL = "Added by hand"


def jl(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


# ------------------------------------------------------------------ rebuild

def _merge_persons(keep_id, drop_id, idx):
    """Two people turned out to be one (a new row bridged them): move everything onto keep_id."""
    keep_events = {e.event_id for e in Entry.query.filter_by(person_id=keep_id)}
    for e in Entry.query.filter_by(person_id=drop_id).all():
        if e.event_id in keep_events:
            db.session.delete(e)
        else:
            e.person_id = keep_id
    keep_att = {a.event_id for a in Attendance.query.filter_by(person_id=keep_id)}
    for a in Attendance.query.filter_by(person_id=drop_id).all():
        if a.event_id in keep_att:
            db.session.delete(a)
        else:
            a.person_id = keep_id
    Person.query.filter_by(id=drop_id).delete()
    for s in idx.values():
        if drop_id in s:
            s.discard(drop_id)
            s.add(keep_id)
    db.session.flush()


def rebuild_event(ev):
    """Recreate this event's merged entries from its raw submissions, keeping person identity and attendance."""
    mp = jl(ev.map, {})
    subs = (
        db.session.query(Submission, Upload)
        .join(Upload, Submission.upload_id == Upload.id)
        .filter(Submission.event_id == ev.id)
        .order_by(Upload.uploaded_at, Upload.id, Submission.id)
        .all()
    )
    items = [(jl(s.row, {}), s.id, u.filename) for s, u in subs]
    records = M.merge_rows(items, mp)

    cols = []
    for row, _sid, _src in items:
        for c in row:
            if c not in cols:
                cols.append(c)
    ev.cols = json.dumps(cols)

    # identity index from every existing entry (this event's old ones included, so people keep their id)
    idx = {}
    for e in Entry.query.all():
        for k in jl(e.keys, []):
            idx.setdefault(tuple(k), set()).add(e.person_id)
    people = {p.id: p for p in Person.query.all()}
    Entry.query.filter_by(event_id=ev.id).delete()
    db.session.flush()

    name_col = mp.get("name")
    taken = {}
    for rec in records:
        ks = M.keys_of(rec["f"], rec["alts"], mp)
        rec_name = rec["f"].get(name_col) if name_col else ""
        cands = set()
        for k in ks:
            for pid in idx.get(k, ()):
                if pid not in people:
                    continue
                if k[0] == "phone" and not M.names_compatible(rec_name, [people[pid].name]):
                    continue
                cands.add(pid)
        if cands:
            pid = min(cands)
            for other in sorted(cands - {pid}):
                _merge_persons(pid, other, idx)
                people.pop(other, None)
            person = people[pid]
        else:
            person = Person()
            db.session.add(person)
            db.session.flush()
            people[person.id] = person
            pid = person.id
        for role, attr in (("name", "name"), ("college", "college"), ("email", "email"), ("phone", "phone")):
            col = mp.get(role)
            v = rec["f"].get(col) if col else ""
            if v:
                setattr(person, attr, v[:250])
        for k in ks:
            idx.setdefault(k, set()).add(pid)
        if pid in taken:
            M.merge_records(taken[pid], rec, mp)
        else:
            taken[pid] = rec

    for pid, rec in taken.items():
        db.session.add(Entry(
            event_id=ev.id, person_id=pid,
            fields=json.dumps(rec["f"]), alts=json.dumps(rec["alts"]),
            keys=json.dumps(M.keys_of(rec["f"], rec["alts"], mp)),
            sids=json.dumps(rec["sids"]), n=rec["n"], first_at=rec["first"], last_at=rec["last"],
        ))
    db.session.flush()

    # attendance only for people still in the event; keep turns 1..n without gaps
    for a in Attendance.query.filter_by(event_id=ev.id).all():
        if a.person_id not in taken:
            db.session.delete(a)
    db.session.flush()
    _renumber(ev.id)
    # people who are in no event any more
    used = db.session.query(Entry.person_id)
    Person.query.filter(~Person.id.in_(used)).delete(synchronize_session=False)
    db.session.commit()


def _renumber(event_id):
    rows = Attendance.query.filter_by(event_id=event_id).order_by(Attendance.turn, Attendance.came_at, Attendance.id).all()
    for i, a in enumerate(rows, 1):
        a.turn = i
    db.session.flush()


# ------------------------------------------------------------------ importing

def canon(headers, rows, imp_map, ev_map):
    """Rename this file's role columns to the event's own column names. Returns (cols, rows(list of dict), final_map)."""
    cols = list(headers)
    final = dict(ev_map or {})
    for r in M.ROLES:
        frm, to = imp_map.get(r), (ev_map or {}).get(r)
        if frm and to and frm != to and to not in cols:
            cols = [to if c == frm else c for c in cols]
    for r in M.ROLES:
        frm = imp_map.get(r)
        if not frm or final.get(r):
            continue
        final[r] = frm
    renamed = {}
    for r in M.ROLES:
        frm, to = imp_map.get(r), (ev_map or {}).get(r)
        if frm and to and frm != to and to not in headers:
            renamed[frm] = to
    out = []
    for row in rows:
        d = {}
        for i, h in enumerate(headers):
            v = M.norm(row[i]) if i < len(row) else ""
            d[renamed.get(h, h)] = v
        out.append(d)
    return cols, out, final


def analyze(headers, rows, imp_map, target_event_id, file_name, skip_cross=False):
    """Does this file look like something already uploaded? Returns a dict describing what was found (or kind=None)."""
    objs = [{h: (r[i] if i < len(r) else "") for i, h in enumerate(headers)} for r in rows]
    incoming = [M.values_fp(o) for o in objs]
    total = len(incoming)
    if not total:
        return {"kind": None, "total": 0}
    found = []
    for ev in Event.query.all():
        sets = {}
        for up_id, vfp in db.session.query(Submission.upload_id, Submission.vfp).filter(Submission.event_id == ev.id):
            sets.setdefault(up_id, set()).add(vfp)
        if not sets:
            continue
        ev_set = set().union(*sets.values())
        best = None
        for up in Upload.query.filter_by(event_id=ev.id).all():
            s = sets.get(up.id, set())
            matched = sum(1 for x in incoming if x in s)
            same = _file_key(up.filename) == _file_key(file_name) and file_name != "Pasted rows"
            if best is None or matched > best["matched"] or (matched == best["matched"] and same):
                best = {"up": up, "matched": matched, "same": same, "rows": len(s) if up.filename != MANUAL else len(s)}
        already = sum(1 for x in incoming if x in ev_set)
        found.append({"ev": ev, "best": best, "already": already, "frac": already / total})

    def pack(f, kind):
        up = f["best"]["up"]
        count = Submission.query.filter_by(upload_id=up.id).count()
        return {
            "kind": kind, "total": total, "already": f["already"], "new_rows": total - f["already"],
            "same_name": f["best"]["same"], "frac": round(f["frac"], 3),
            "event": {"id": f["ev"].id, "name": f["ev"].name},
            "upload": {"id": up.id, "filename": up.filename, "uploaded_at": up.uploaded_at, "rows": count},
        }

    if not skip_cross:
        cross = sorted((f for f in found if f["ev"].id != target_event_id and f["best"] and f["frac"] >= 0.6),
                       key=lambda f: -f["frac"])
        if cross:
            return pack(cross[0], "cross")
    tf = next((f for f in found if f["ev"].id == target_event_id), None)
    if tf and tf["best"] and tf["best"]["up"].filename != MANUAL and (tf["frac"] >= 0.6 or tf["best"]["same"]):
        return pack(tf, "same")
    return {"kind": None, "total": total}


def _file_key(name):
    import re
    s = (name or "").lower()
    s = re.sub(r"\.[a-z0-9]+$", "", s)
    s = re.sub(r"[\s_-]*(\(\d+\)|copy|final|new|latest|updated)$", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def commit_import(event_id, new_name, file_name, headers, rows, imp_map, mode, replace_upload_id=None):
    if event_id:
        ev = db.session.get(Event, event_id)
    else:
        ev = Event(name=new_name.strip(), map=json.dumps({k: v for k, v in imp_map.items() if v}))
        db.session.add(ev)
        db.session.flush()
    ev_map = jl(ev.map, {})
    before_people = Entry.query.filter_by(event_id=ev.id).count()
    cols, objs, final = canon(headers, rows, imp_map, ev_map)
    if final != ev_map:
        ev.map = json.dumps(final)

    skipped = 0
    if mode == "new":
        have = {v for (v,) in db.session.query(Submission.vfp).filter_by(event_id=ev.id)}
        keep = []
        for o in objs:
            if M.values_fp(o) in have:
                skipped += 1
            else:
                keep.append(o)
        objs = keep

    removed = ""
    if mode == "replace" and replace_upload_id:
        up = db.session.get(Upload, replace_upload_id)
        if up and up.event_id == ev.id:
            removed = up.filename
            Submission.query.filter_by(upload_id=up.id).delete()
            db.session.delete(up)
            db.session.flush()

    if objs:
        up = Upload(event_id=ev.id, filename=file_name[:250])
        db.session.add(up)
        db.session.flush()
        db.session.add_all(Submission(event_id=ev.id, upload_id=up.id, row=json.dumps(o), vfp=M.values_fp(o)) for o in objs)
    db.session.flush()
    rebuild_event(ev)
    after = Entry.query.filter_by(event_id=ev.id).count()
    return {
        "event": {"id": ev.id, "name": ev.name}, "rows": len(objs),
        "new_people": max(0, after - before_people), "merged": max(0, len(objs) - max(0, after - before_people)),
        "skipped": skipped, "removed": removed,
    }


def remove_upload(event_id, upload_id):
    ev = db.session.get(Event, event_id)
    up = db.session.get(Upload, upload_id)
    if not ev or not up or up.event_id != event_id:
        return False
    Submission.query.filter_by(upload_id=up.id).delete()
    db.session.delete(up)
    db.session.flush()
    rebuild_event(ev)
    return True


def delete_event(event_id):
    ev = db.session.get(Event, event_id)
    if not ev:
        return
    for model in (Attendance, Entry, Submission, Upload):
        model.query.filter_by(event_id=event_id).delete()
    db.session.delete(ev)
    db.session.flush()
    used = db.session.query(Entry.person_id)
    Person.query.filter(~Person.id.in_(used)).delete(synchronize_session=False)
    db.session.commit()


# ------------------------------------------------------------------ add one person by hand

def add_person(event_ids, values, extra, came):
    """Add one person to one or more events. Returns a list of per-event results."""
    results = []
    stamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for eid in event_ids:
        ev = db.session.get(Event, eid)
        if not ev:
            continue
        mp = jl(ev.map, {})
        if not mp:
            mp = dict(DEFAULT_MAP)
            ev.map = json.dumps(mp)
        row = {}
        for role in CORE:
            col = mp.get(role)
            if not col and values.get(role):
                col = DEFAULT_MAP[role]
                if col in jl(ev.cols, []):
                    col = DEFAULT_MAP[role] + " (added)"
                mp[role] = col
                ev.map = json.dumps(mp)
            if col:
                row[col] = M.norm(values.get(role, ""))
        known = jl(ev.cols, [])
        for col, v in (extra or {}).items():
            if col in known and col not in row and M.norm(v):
                row[col] = M.norm(v)
        if mp.get("time"):
            row[mp["time"]] = stamp
        up = Upload.query.filter_by(event_id=ev.id, filename=MANUAL).first()
        if not up:
            up = Upload(event_id=ev.id, filename=MANUAL)
            db.session.add(up)
            db.session.flush()
        sub = Submission(event_id=ev.id, upload_id=up.id, row=json.dumps(row), vfp=M.values_fp(row))
        db.session.add(sub)
        db.session.flush()
        rebuild_event(ev)
        entry = next((e for e in Entry.query.filter_by(event_id=ev.id) if sub.id in jl(e.sids, [])), None)
        merged = bool(entry and entry.n > 1)
        if came and entry:
            set_came(ev.id, entry.person_id, True)
        results.append({"event_id": ev.id, "event": ev.name, "person_id": entry.person_id if entry else None, "merged": merged})
    return results


# ------------------------------------------------------------------ attendance and turn order

def set_came(event_id, person_id, came):
    att = Attendance.query.filter_by(event_id=event_id, person_id=person_id).first()
    if came and not att:
        if not Entry.query.filter_by(event_id=event_id, person_id=person_id).first():
            return False
        top = db.session.query(func.max(Attendance.turn)).filter_by(event_id=event_id).scalar() or 0
        db.session.add(Attendance(event_id=event_id, person_id=person_id, came_at=now_ms(), turn=top + 1))
    elif not came and att:
        db.session.delete(att)
        db.session.flush()
        _renumber(event_id)
    db.session.commit()
    return True


def move_turn(event_id, person_id, to):
    rows = Attendance.query.filter_by(event_id=event_id).order_by(Attendance.turn).all()
    me = next((a for a in rows if a.person_id == person_id), None)
    if not me:
        return False
    rows.remove(me)
    to = max(1, min(int(to), len(rows) + 1))
    rows.insert(to - 1, me)
    # two passes avoid hitting any uniqueness on 'turn' if one is ever added
    for i, a in enumerate(rows, 1):
        a.turn = i
    db.session.commit()
    return True


# ------------------------------------------------------------------ reading

def event_stats(ev_id):
    people = Entry.query.filter_by(event_id=ev_id).count()
    came = Attendance.query.filter_by(event_id=ev_id).count()
    repeats = db.session.query(func.coalesce(func.sum(Entry.n - 1), 0)).filter(Entry.event_id == ev_id).scalar() or 0
    return {"people": people, "came": came, "not_yet": people - came, "repeats": int(repeats)}


def summary():
    people = Person.query.count()
    came_any = db.session.query(func.count(func.distinct(Attendance.person_id))).scalar() or 0
    repeats = db.session.query(func.coalesce(func.sum(Entry.n - 1), 0)).scalar() or 0
    return {"people": people, "events": Event.query.count(), "came_any": came_any, "repeats": int(repeats)}


def events_overview():
    out = []
    for ev in Event.query.order_by(Event.created_at, Event.id).all():
        d = {"id": ev.id, "name": ev.name, "created_at": ev.created_at, "cols": jl(ev.cols, []), "map": jl(ev.map, {})}
        d.update(event_stats(ev.id))
        out.append(d)
    return out


def event_detail(ev):
    d = {"id": ev.id, "name": ev.name, "cols": jl(ev.cols, []), "map": jl(ev.map, {})}
    d.update(event_stats(ev.id))
    ups = []
    for up in Upload.query.filter_by(event_id=ev.id).order_by(Upload.uploaded_at, Upload.id).all():
        ups.append({"id": up.id, "filename": up.filename, "uploaded_at": up.uploaded_at,
                    "rows": Submission.query.filter_by(upload_id=up.id).count()})
    d["uploads"] = ups
    return d


def list_people(event_id=None, q="", status="all", person_id=None):
    """People rows for the home page. With event_id: that event's entries. Without: everyone, once each."""
    events = {e.id: e for e in Event.query.all()}
    entries_q = Entry.query
    if event_id:
        entries_q = entries_q.filter_by(event_id=event_id)
    entries = entries_q.order_by(Entry.id).all()
    att = {(a.event_id, a.person_id): a for a in Attendance.query.all()}
    people = {p.id: p for p in Person.query.all()}
    by_person = {}
    for e in Entry.query.order_by(Entry.event_id, Entry.id).all():
        by_person.setdefault(e.person_id, []).append(e)

    def event_tags(pid):
        tags = []
        for e in by_person.get(pid, []):
            a = att.get((e.event_id, pid))
            tags.append({"event_id": e.event_id, "name": events[e.event_id].name if e.event_id in events else "",
                         "came": bool(a), "turn": a.turn if a else None, "came_at": a.came_at if a else None, "n": e.n})
        return tags

    toks = M.tokenize(q)
    rows, seen = [], set()
    for e in entries:
        pid = e.person_id
        if event_id is None:
            if pid in seen:
                continue
            seen.add(pid)
        p = people.get(pid)
        if not p:
            continue
        tags = event_tags(pid)
        if event_id:
            fields, alts = jl(e.fields, {}), jl(e.alts, {})
            a = att.get((event_id, pid))
            came, turn, came_at, n = bool(a), (a.turn if a else None), (a.came_at if a else None), e.n
            parts = list(fields.values()) + [v for lst in alts.values() for v in lst]
        else:
            fields = {"name": p.name, "college": p.college, "email": p.email, "phone": p.phone}
            alts = {}
            came = any(t["came"] for t in tags)
            turn, came_at = None, None
            n = max([t["n"] for t in tags] + [1])  # repeats inside one event, not the number of events
            parts = [p.name, p.college, p.email, p.phone]
            for pe in by_person.get(pid, []):
                parts += list(jl(pe.fields, {}).values())
                parts += [v for lst in jl(pe.alts, {}).values() for v in lst]
        parts += [t["name"] for t in tags]
        if person_id and pid != person_id:
            continue
        if not M.matches(M.haystack(parts), toks):
            continue
        merged = any(t["n"] > 1 for t in tags) if not event_id else e.n > 1
        if status == "came" and not came:
            continue
        if status == "wait" and came:
            continue
        if status == "merged" and not merged:
            continue
        rows.append({"person_id": pid, "name": p.name, "college": p.college, "email": p.email, "phone": p.phone,
                     "fields": fields, "alts": alts, "n": n, "merged": merged, "came": came, "turn": turn,
                     "came_at": came_at, "events": tags})
    return rows


def person_detail(pid):
    p = db.session.get(Person, pid)
    if not p:
        return None
    out = {"id": p.id, "name": p.name, "college": p.college, "email": p.email, "phone": p.phone, "events": []}
    att = {a.event_id: a for a in Attendance.query.filter_by(person_id=pid)}
    for e in Entry.query.filter_by(person_id=pid).order_by(Entry.event_id).all():
        ev = db.session.get(Event, e.event_id)
        a = att.get(e.event_id)
        files = sorted({u.filename for u in db.session.query(Upload).join(Submission, Submission.upload_id == Upload.id)
                        .filter(Submission.id.in_(jl(e.sids, [])))})
        out["events"].append({
            "event_id": e.event_id, "name": ev.name, "cols": jl(ev.cols, []), "fields": jl(e.fields, {}),
            "alts": jl(e.alts, {}), "n": e.n, "first_at": e.first_at, "last_at": e.last_at,
            "came": bool(a), "turn": a.turn if a else None, "came_at": a.came_at if a else None, "files": files,
        })
    return out


def turn_list(event_id):
    ev = db.session.get(Event, event_id)
    if not ev:
        return None
    rows = []
    mp = jl(ev.map, {})
    entries = {e.person_id: e for e in Entry.query.filter_by(event_id=event_id)}
    for a in Attendance.query.filter_by(event_id=event_id).order_by(Attendance.turn).all():
        p = db.session.get(Person, a.person_id)
        e = entries.get(a.person_id)
        rows.append({"person_id": a.person_id, "turn": a.turn, "came_at": a.came_at, "name": p.name, "college": p.college,
                     "email": p.email, "phone": p.phone, "n": e.n if e else 1})
    stats = event_stats(event_id)
    return {"event": {"id": ev.id, "name": ev.name}, "turns": rows, "stats": stats}
