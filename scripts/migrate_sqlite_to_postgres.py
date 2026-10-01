"""Copy the SQLite database into Postgres and verify the copy row-for-row.

Usage (from the project root, with DATABASE_URL set in .env or the environment):
    python scripts/migrate_sqlite_to_postgres.py            # copy, then verify
    python scripts/migrate_sqlite_to_postgres.py --verify   # only compare the two databases
    python scripts/migrate_sqlite_to_postgres.py --replace  # wipe non-empty Postgres tables first

The SQLite file is opened read-only and is never modified. The copy runs in one
transaction: if any row fails, Postgres is left exactly as it was.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

# Parents before children so the ticket_items foreign key is satisfied.
TABLES = ("ticket_records", "ticket_items", "docket_records", "csv_rows", "upload_audits", "csv_imports",
          "unassigned_screenshots", "upload_hashes", "extraction_jobs")
IDENTITY_TABLES = ("ticket_items", "docket_records", "csv_rows", "upload_audits")
PRIMARY_KEYS = {"ticket_records": "ticket_id", "unassigned_screenshots": "filename", "extraction_jobs": "job_id",
                "csv_imports": "branch, selected_date", "upload_hashes": "kind, file_hash"}


def _sqlite(path: Path):
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _pg_columns(pg, table):
    rows = pg.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=?", (table,)).fetchall()
    return {row["column_name"]: row["data_type"] for row in rows}


def _coerce(value, pg_type):
    """SQLite allows any value in any column; give Postgres the declared type."""
    if value is None:
        return None
    if pg_type == "text":
        return value if isinstance(value, str) else str(value)
    if pg_type in ("integer", "bigint"):
        return int(value)
    if pg_type == "double precision":
        return float(value)
    return value


def _order_by(table):
    return PRIMARY_KEYS.get(table, "id")


def _fingerprint(rows, columns):
    """Order-independent digest of the given columns, normalising numbers so
    SQLite integers stored in REAL columns compare equal to Postgres floats."""
    digest = hashlib.sha256()
    lines = []
    for row in rows:
        values = []
        for column in columns:
            value = row[column]
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            values.append(value)
        lines.append(json.dumps(values, ensure_ascii=False, default=str))
    for line in sorted(lines):
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def copy(lite, pg, replace):
    from app.storage import db

    db.init_db()  # creates the Postgres schema if it does not exist yet
    non_empty = [t for t in TABLES if pg.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]]
    if non_empty and not replace:
        sys.exit(f"Postgres already has data in: {', '.join(non_empty)}. Re-run with --replace to overwrite it.")
    if non_empty:
        pg.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")

    for table in TABLES:
        source_columns = [row["name"] for row in lite.execute(f"PRAGMA table_info({table})")]
        if not source_columns:
            print(f"  {table:24} not in SQLite, skipped")
            continue
        target = _pg_columns(pg, table)
        missing = [c for c in source_columns if c not in target]
        if missing:
            sys.exit(f"{table}: Postgres schema lacks columns {missing}; nothing was copied.")
        rows = lite.execute(f"SELECT {', '.join(source_columns)} FROM {table}").fetchall()
        placeholders = ", ".join("?" * len(source_columns))
        pg.executemany(
            f"INSERT INTO {table} ({', '.join(source_columns)}) VALUES ({placeholders})",
            [[_coerce(row[c], target[c]) for c in source_columns] for row in rows],
        )
        print(f"  {table:24} {len(rows):6} rows copied")

    for table in IDENTITY_TABLES:
        pg.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 0) + 1, false) FROM {table}")
    pg.commit()


def verify(lite, pg):
    ok = True
    print(f"  {'table':24} {'sqlite':>7} {'postgres':>9}  content")
    for table in TABLES:
        source_columns = [row["name"] for row in lite.execute(f"PRAGMA table_info({table})")]
        if not source_columns:
            continue
        target = _pg_columns(pg, table)
        shared = [c for c in source_columns if c in target]
        lite_rows = [dict(r) for r in lite.execute(f"SELECT {', '.join(shared)} FROM {table}")]
        pg_rows = pg.execute(f"SELECT {', '.join(shared)} FROM {table}").fetchall()
        same_count = len(lite_rows) == len(pg_rows)
        normalised_lite = [{c: _coerce(r[c], target[c]) for c in shared} for r in lite_rows]
        same_content = _fingerprint(normalised_lite, shared) == _fingerprint(pg_rows, shared)
        status = "identical" if same_count and same_content else "DIFFERENT"
        ok = ok and same_count and same_content and len(shared) == len(source_columns)
        print(f"  {table:24} {len(lite_rows):7} {len(pg_rows):9}  {status}")
    if "ticket_items" in TABLES:
        orphans = pg.execute("SELECT COUNT(*) AS n FROM ticket_items WHERE ticket_id NOT IN (SELECT ticket_id FROM ticket_records)").fetchone()["n"]
        ok = ok and orphans == 0
    for table in IDENTITY_TABLES:
        row = pg.execute(f"SELECT COALESCE(MAX(id), 0) AS max_id, (SELECT last_value FROM {table}_id_seq) AS next_id FROM {table}").fetchone()
        if row["next_id"] < row["max_id"]:
            print(f"  {table}: id sequence ({row['next_id']}) is behind max id ({row['max_id']})")
            ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", default=str(PROJECT_ROOT / "data" / "til_system.db"))
    parser.add_argument("--postgres", help="Postgres URL (default: DATABASE_URL from .env/environment)")
    parser.add_argument("--verify", action="store_true", help="only compare, do not copy")
    parser.add_argument("--replace", action="store_true", help="overwrite existing Postgres data")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    if args.postgres:
        os.environ["DATABASE_URL"] = args.postgres
    from app.storage import db

    if not db.is_postgres():
        sys.exit("Set DATABASE_URL (or pass --postgres) to a postgresql:// URL.")
    sqlite_path = Path(args.sqlite)
    if not sqlite_path.is_file():
        sys.exit(f"SQLite database not found: {sqlite_path}")

    lite = _sqlite(sqlite_path)
    with db.get_db_connection() as pg:
        if not args.verify:
            print(f"Copying {sqlite_path} -> Postgres")
            copy(lite, pg, args.replace)
        print("Verifying")
        ok = verify(lite, pg)
    lite.close()
    print("MIGRATION VERIFIED: Postgres matches SQLite." if ok else "VERIFICATION FAILED: see DIFFERENT rows above.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
