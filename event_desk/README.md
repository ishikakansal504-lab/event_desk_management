# Event Desk

One website for many events. Upload registrations (Excel, CSV or pasted rows), repeat form entries are
merged, the same person across events is one person, tick who came, and see people in first-come turn order.
Data is stored in a real database (MySQL, or SQLite for a quick start), so it works in any browser.

## Run it

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python app.py                  # open http://127.0.0.1:5000
```

With no settings it saves to a local file `eventdesk.db` (SQLite). Nothing else to install.

## Use MySQL

1. Create the database and a user (MySQL Workbench, or the `mysql` command line):

```sql
CREATE DATABASE eventdesk CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'eventdesk'@'localhost' IDENTIFIED BY 'YOUR_PASSWORD';
GRANT ALL PRIVILEGES ON eventdesk.* TO 'eventdesk'@'localhost';
FLUSH PRIVILEGES;
```

2. Point the app at it, then start it (the tables are created automatically on first start):

```bash
set DATABASE_URL=mysql+pymysql://eventdesk:YOUR_PASSWORD@localhost:3306/eventdesk?charset=utf8mb4     # Windows cmd
export DATABASE_URL="mysql+pymysql://eventdesk:YOUR_PASSWORD@localhost:3306/eventdesk?charset=utf8mb4" # Mac/Linux
python app.py
```

## Let volunteers use it on their phones

Run with `HOST=0.0.0.0` on a computer on the same Wi-Fi and open `http://<that computer's IP>:5000`,
or deploy it to a host that runs Python (for production use `gunicorn app:app`). Set `APP_PASSWORD`
so only your team can open it. Open pages refresh themselves every few seconds, so ticks made on one
phone show up on the others.

## How it works

| Part | What it does |
| --- | --- |
| `app.py` | Web server and JSON API |
| `merge.py` | Finds repeat entries: same email, same phone (with a matching name), or same name + college |
| `services.py` | Import, "is this the same file?" check, people across events, attendance, turn order |
| `exports.py` | Excel and PDF downloads |
| `models.py` | Database tables (events, uploads, submissions, people, entries, attendance) |
| `static/` | The pages you see (People, Turn order) |

- Raw uploaded rows are always kept, so removing or replacing a file rebuilds the people list without losing
  attendance or turn order.
- When a new upload looks like an earlier one, you are asked first, with the file and event named.
- Turn order is first-come: ticking someone puts them at the end. Move anyone to any position on the Turn order page.
- Run the checks with `python tests/test_api.py`.

Not covered: old `.xls` files (save as `.xlsx` first). PDF uses a basic font unless `FONT_PATH` points to one that supports your script.
