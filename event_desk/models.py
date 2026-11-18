from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import BigInteger, Text, UniqueConstraint
from sqlalchemy.dialects import mysql

db = SQLAlchemy()

# MySQL's TEXT holds only 64 KB; use LONGTEXT there for big sheets, plain TEXT elsewhere.
LongText = Text().with_variant(mysql.LONGTEXT(), "mysql")


def now_ms():
    return int(datetime.now().timestamp() * 1000)


class Event(db.Model):
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(BigInteger, default=now_ms)
    map = db.Column(Text, default="{}")      # JSON: role -> column name (name, college, email, phone, time)
    cols = db.Column(LongText, default="[]")  # JSON: column names, in order


class Upload(db.Model):
    """One uploaded file (or the 'Added by hand' list) belonging to an event."""
    __tablename__ = "uploads"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), index=True, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(BigInteger, default=now_ms)


class Submission(db.Model):
    """One raw form row, exactly as uploaded. People are rebuilt from these."""
    __tablename__ = "submissions"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), index=True, nullable=False)
    upload_id = db.Column(db.Integer, db.ForeignKey("uploads.id"), index=True, nullable=False)
    row = db.Column(LongText, nullable=False)  # JSON object column -> value
    vfp = db.Column(db.String(32), index=True)  # content fingerprint used to spot re-uploads


class Person(db.Model):
    """One real person. The same person can be in many events."""
    __tablename__ = "people"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), default="")
    college = db.Column(db.String(255), default="")
    email = db.Column(db.String(255), default="")
    phone = db.Column(db.String(64), default="")


class Entry(db.Model):
    """A person's merged registration in one event (rebuilt from submissions)."""
    __tablename__ = "entries"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), index=True, nullable=False)
    person_id = db.Column(db.Integer, db.ForeignKey("people.id"), index=True, nullable=False)
    fields = db.Column(LongText, default="{}")  # JSON latest answers
    alts = db.Column(LongText, default="{}")    # JSON older different answers
    keys = db.Column(LongText, default="[]")    # JSON identity keys
    sids = db.Column(LongText, default="[]")    # JSON submission ids merged into this entry
    n = db.Column(db.Integer, default=1)        # how many times the form was filled
    first_at = db.Column(BigInteger)
    last_at = db.Column(BigInteger)
    __table_args__ = (UniqueConstraint("event_id", "person_id", name="uq_entry_event_person"),)


class Attendance(db.Model):
    """Exists only for people who have come. 'turn' is first-come order inside the event."""
    __tablename__ = "attendance"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), index=True, nullable=False)
    person_id = db.Column(db.Integer, db.ForeignKey("people.id"), index=True, nullable=False)
    came_at = db.Column(BigInteger, default=now_ms)
    turn = db.Column(db.Integer, nullable=False)
    __table_args__ = (UniqueConstraint("event_id", "person_id", name="uq_att_event_person"),)
