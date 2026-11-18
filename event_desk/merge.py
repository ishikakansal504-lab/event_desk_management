"""Duplicate detection and merging.

Two form entries are treated as the same person when they share an email, a phone number
(and a compatible name), or the same name + college. Merged entries keep the latest answer
for each field and remember older, different answers as "alts".
"""
import hashlib
import math
import re
from datetime import datetime

try:
    from dateutil import parser as _dateparser
except Exception:  # dateutil is optional
    _dateparser = None

ROLES = ["name", "college", "email", "phone", "time"]


def norm(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def alnum(v):
    return re.sub(r"[^a-z0-9]+", "", norm(v).lower())


def norm_email(v):
    s = norm(v).lower()
    return s if re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", s) else ""


def norm_phone(v):
    d = re.sub(r"\D+", "", norm(v))
    return d[-10:] if len(d) >= 10 else ""


def name_tokens(v):
    return [t for t in re.split(r"[^a-z0-9]+", norm(v).lower()) if len(t) >= 3]


def names_compatible(a, others):
    A = name_tokens(a)
    if not A:
        return True
    lst = [o for o in others if o]
    if not lst:
        return True
    for o in lst:
        B = name_tokens(o)
        if not B or any(t in B for t in A):
            return True
    return False


def _hash(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]


def row_fp(row):
    """Identifies a row inside one event (depends on column names)."""
    return _hash("\x02".join(k + "\x01" + norm(row[k]) for k in sorted(row)))


def values_fp(row):
    """Identifies a row's content regardless of column names or order (to compare files)."""
    return _hash("|".join(sorted(x for x in (alnum(v) for v in row.values()) if x)))


# ---------------------------------------------------------------- tables

def prepare_table(rows2d):
    """rows2d: list of lists. Finds the header row (skips title rows) and returns (headers, rows)."""
    rows = [[norm(c) for c in (r or [])] for r in rows2d]
    probe = rows[:15]
    filled = lambda r: sum(1 for c in r if c)
    mx = max([filled(r) for r in probe] + [0])
    need = max(2, math.ceil(mx * 0.6))
    h = next((i for i, r in enumerate(probe) if filled(r) >= need), 0)
    head = rows[h] if rows else []
    body = [r for r in rows[h + 1:] if filled(r) > 0]
    width = max([len(head)] + [len(r) for r in body] + [0])
    used = [c for c in range(width) if (c < len(head) and head[c]) or any(c < len(r) and r[c] for r in body)]
    seen, headers = {}, []
    for c in used:
        name = head[c] if c < len(head) and head[c] else "Column %d" % (c + 1)
        k = name.lower()
        seen[k] = seen.get(k, 0) + 1
        headers.append(name if seen[k] == 1 else "%s (%d)" % (name, seen[k]))
    out = [[(r[c] if c < len(r) else "") for c in used] for r in body]
    return headers, out


def detect_roles(headers):
    def pick(test, nt=None):
        for h in headers:
            if re.search(test, h, re.I) and not (nt and re.search(nt, h, re.I)):
                return h
        return ""

    m = {}
    m["email"] = pick(r"e-?mail")
    m["phone"] = pick(r"(phone|mobile|whats ?app|contact\s*(no|num)|cell)", r"(roll|enrol|regist|\bid\b)")
    m["college"] = pick(r"(college|institut|universit|school|organi[sz]ation|campus)")
    not_name = r"(college|institut|universit|school|team name|event|father|mother|organi)"
    m["name"] = pick(
        r"^(full\s*|your\s*|student\s*|participant\s*|candidate\s*|team\s*leader\s*)?name\b|name of (the )?(participant|student|candidate)",
        not_name,
    ) or pick(r"name", r"(college|institut|universit|school|team|event|father|mother|organi|file)")
    m["time"] = pick(r"(timestamp|time stamp|submitted|submission)")
    return {k: v for k, v in m.items() if v}


def parse_ts(v):
    """Returns milliseconds since epoch (naive local time) or None."""
    s = norm(v)
    if not s:
        return None
    s = re.sub(r"\s*(GMT|UTC)\s*[+-]?[\d:]*$", "", s, flags=re.I)
    m = re.match(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})(?:[ ,T]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?)?", s, re.I)
    try:
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hh, mi, ss = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
            ap = (m.group(7) or "").lower()
            if y < 100:
                y += 2000
            if ap == "pm" and hh < 12:
                hh += 12
            if ap == "am" and hh == 12:
                hh = 0
            return int(datetime(y, mo, d, hh, mi, ss).timestamp() * 1000)
        try:
            return int(datetime.fromisoformat(s.replace("/", "-")).timestamp() * 1000)
        except ValueError:
            pass
        if _dateparser:
            return int(_dateparser.parse(s, dayfirst=True).timestamp() * 1000)
    except Exception:
        return None
    return None


# ---------------------------------------------------------------- merging

def keys_of(f, alts, mp):
    """Identity keys of a row/record: list of (kind, value)."""
    def vals(col):
        if not col:
            return []
        return [f.get(col)] + list((alts or {}).get(col, []))

    emails = [e for e in (norm_email(x) for x in vals(mp.get("email"))) if e]
    phones = [p for p in (norm_phone(x) for x in vals(mp.get("phone"))) if p]
    name = alnum(f.get(mp.get("name"))) if mp.get("name") else ""
    college = alnum(f.get(mp.get("college"))) if mp.get("college") else ""
    out = [("email", e) for e in emails] + [("phone", p) for p in phones]
    if name and college:
        out.append(("nc", name + "|" + college))
    if name and not emails and not phones and not college:
        out.append(("n", name))
    return out


def _same_value(col, a, b, mp):
    if col == mp.get("phone"):
        x, y = norm_phone(a), norm_phone(b)
        if x and y:
            return x == y
    if col == mp.get("email"):
        return norm(a).lower() == norm(b).lower()
    return alnum(a) == alnum(b)


def _set_value(rec, col, v, newer, mp):
    v = norm(v)
    if not v:
        return
    cur = rec["f"].get(col)
    if not cur:
        rec["f"][col] = v
        return
    if _same_value(col, cur, v, mp):
        if newer:
            rec["f"][col] = v
        return
    alts = rec["alts"].setdefault(col, [])

    def add(x):
        if not any(_same_value(col, a, x, mp) for a in alts):
            alts.append(x)

    if newer:
        add(cur)
        rec["f"][col] = v
    else:
        add(v)
    rec["alts"][col] = [a for a in alts if not _same_value(col, a, rec["f"][col], mp)]
    if not rec["alts"][col]:
        del rec["alts"][col]


def _stamp(rec, first, last):
    if first is not None and (rec["first"] is None or first < rec["first"]):
        rec["first"] = first
    if last is not None and (rec["last"] is None or last > rec["last"]):
        rec["last"] = last


def merge_records(target, other, mp):
    newer = True if (other["last"] is None or target["last"] is None) else other["last"] >= target["last"]
    for col, v in other["f"].items():
        _set_value(target, col, v, newer, mp)
    for col, lst in other["alts"].items():
        for a in lst:
            _set_value(target, col, a, False, mp)
    target["n"] += other["n"]
    _stamp(target, other["first"], other["last"])
    target["fps"] += other["fps"]
    target["sids"] += other["sids"]
    for s in other["src"]:
        if s not in target["src"]:
            target["src"].append(s)


def _absorb(rec, row, ts, fp, sid, source, mp):
    newer = ts is None or rec["last"] is None or ts >= rec["last"]
    for col, v in row.items():
        _set_value(rec, col, v, newer, mp)
    rec["n"] += 1
    _stamp(rec, ts, ts)
    rec["fps"].append(fp)
    if sid is not None:
        rec["sids"].append(sid)
    if source and source not in rec["src"]:
        rec["src"].append(source)


def merge_rows(items, mp):
    """items: list of (row_dict, submission_id, source_name) in upload order.
    Returns a list of merged records."""
    records, alive, order = [], {}, {}
    idx = {"email": {}, "phone": {}, "nc": {}, "n": {}}

    def index(rec):
        for k, v in keys_of(rec["f"], rec["alts"], mp):
            idx[k].setdefault(v, set()).add(rec["id"])

    name_col = mp.get("name")
    for row, sid, source in items:
        fp = row_fp(row)
        ts = parse_ts(row.get(mp["time"])) if mp.get("time") else None
        cand = {}
        for k, v in keys_of(row, None, mp):
            for rid in idx[k].get(v, ()):
                r = alive.get(rid)
                if r is None:
                    continue
                if k == "phone" and name_col and not names_compatible(
                    row.get(name_col), [r["f"].get(name_col)] + r["alts"].get(name_col, [])
                ):
                    continue
                cand[rid] = r
        if not cand:
            rid, n = fp, 1
            while rid in alive:
                rid = "%s-%d" % (fp, n)
                n += 1
            rec = {"id": rid, "f": {}, "alts": {}, "n": 0, "first": None, "last": None, "fps": [], "sids": [], "src": []}
            _absorb(rec, row, ts, fp, sid, source, mp)
            records.append(rec)
            alive[rid] = rec
            order[rid] = len(order)
            index(rec)
        else:
            lst = sorted(cand.values(), key=lambda r: order[r["id"]])
            target = lst[0]
            for o in lst[1:]:
                merge_records(target, o, mp)
                del alive[o["id"]]
            _absorb(target, row, ts, fp, sid, source, mp)
            index(target)
    return [r for r in records if r["id"] in alive]


# ---------------------------------------------------------------- search

def tokenize(q):
    return [t for t in norm(q).lower().split(" ") if t]


def haystack(parts):
    text = " \x01 ".join(p for p in parts if p).lower()
    return text, re.sub(r"[^a-z0-9]+", "", text)


def matches(hay, toks):
    if not toks:
        return True
    text, flat = hay
    for t in toks:
        if t in text:
            continue
        f = re.sub(r"[^a-z0-9]", "", t)
        if len(f) >= 4 and re.search(r"\d", f) and f in flat:
            continue
        return False
    return True
