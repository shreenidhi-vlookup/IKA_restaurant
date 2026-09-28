import sqlite3
import os
import typing as t
import json
from contextlib import contextmanager
from datetime import datetime
from app.models.entry import EntryInDBBase
from app.models.sales_report import canonical_date_key

DATABASE_PATH = "./data/til_system.db"

@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialize the database with the entries table."""
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

    with get_db_connection() as conn:
        # Create table if it doesn't exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant TEXT NOT NULL,
                ticket_number TEXT NOT NULL,
                discrepancy_type TEXT NOT NULL,
                extracted_text TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL,
                extra_fields TEXT,
                image_filename TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_records (
                ticket_id TEXT PRIMARY KEY,
                ticket_id_display TEXT NOT NULL,
                restaurant TEXT,
                phone TEXT,
                ticket_date TEXT,
                terminal TEXT,
                table_name TEXT,
                department TEXT,
                user_name TEXT,
                payment_status TEXT,
                credit_card_amount TEXT,
                ticket_total TEXT,
                grand_total TEXT,
                charged TEXT,
                extra_fields TEXT,
                items TEXT NOT NULL,
                screenshot_filenames TEXT NOT NULL,
                raw_texts TEXT NOT NULL,
                extraction_method TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS docket_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                docket_order_no TEXT,
                docket_date TEXT,
                docket_time TEXT,
                item TEXT,
                discrepancy_type TEXT,
                handwritten_reason TEXT,
                printed_text TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                extra_fields TEXT,
                image_filename TEXT NOT NULL,
                review_required INTEGER NOT NULL DEFAULT 0,
                review_reason TEXT,
                extraction_method TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL REFERENCES ticket_records(ticket_id) ON DELETE CASCADE,
                item TEXT,
                category TEXT,
                price TEXT,
                qty TEXT,
                total TEXT,
                is_void INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant TEXT NOT NULL,
                report_date TEXT,
                departments TEXT NOT NULL,
                source TEXT NOT NULL,
                cross_verified INTEGER NOT NULL DEFAULT 0,
                confirmed_source TEXT,
                image_filename TEXT,
                extracted_text TEXT,
                extraction_method TEXT,
                extra_fields TEXT,
                excel_filename TEXT,
                excel_summary TEXT,
                excel_skipped_rows INTEGER NOT NULL DEFAULT 0,
                excel_void_rows INTEGER NOT NULL DEFAULT 0,
                excel_unfilled_rows INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Source 2: the Excel Daily Exception Report is a row-level audit log,
        # so it needs its own rows rather than a department-total blob.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_exception_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL REFERENCES sales_reports(id) ON DELETE CASCADE,
                row_date TEXT,
                branch TEXT,
                bill_number TEXT,
                item TEXT,
                quantity TEXT,
                amount REAL,
                adjustment_type TEXT,
                adjustment TEXT,
                food_status TEXT,
                payment_status TEXT,
                cashier_name TEXT,
                approving_manager TEXT,
                reason TEXT,
                posted_in_group_chat TEXT,
                docket_photo_attached TEXT,
                proof TEXT,
                audit_status TEXT
            )
        """)

        # Add extra_fields column if it doesn't exist (for existing databases) -- JSON string for extra fields
        try:
            conn.execute("ALTER TABLE entries ADD COLUMN extra_fields TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists, which is fine
            pass

        # Add image_filename column if it doesn't exist
        try:
            conn.execute("ALTER TABLE entries ADD COLUMN image_filename TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists, which is fine
            pass

        # Add blocks column (JSON) if it doesn't exist
        try:
            conn.execute("ALTER TABLE entries ADD COLUMN blocks TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            # Column already exists, which is fine
            pass

        # Add extraction_method column if it doesn't exist (for existing databases)
        for table in ("ticket_records", "docket_records"):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN extraction_method TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                # Column already exists, which is fine
                pass

        # Source 2 (Excel Daily Exception Report) metadata, additive.
        for column, ddl in (
            ("excel_filename", "TEXT"),
            ("excel_summary", "TEXT"),
            ("excel_skipped_rows", "INTEGER NOT NULL DEFAULT 0"),
            ("excel_void_rows", "INTEGER NOT NULL DEFAULT 0"),
            ("excel_unfilled_rows", "INTEGER NOT NULL DEFAULT 0"),
        ):
            try:
                conn.execute(f"ALTER TABLE sales_reports ADD COLUMN {column} {ddl}")
                conn.commit()
            except sqlite3.OperationalError:
                # Column already exists, which is fine
                pass

        conn.commit()

def create_entry(entry: EntryInDBBase) -> int:
    """Create a new entry and return its ID."""
    with get_db_connection() as conn:
        extra_fields_json = json.dumps(entry.extra_fields) if entry.extra_fields else None
        blocks_json = json.dumps(entry.blocks) if entry.blocks else None

        cursor = conn.execute("""
            INSERT INTO entries (restaurant, ticket_number, discrepancy_type, extracted_text, description, status, extra_fields, blocks, image_filename)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.restaurant,
            entry.ticket_number,
            entry.discrepancy_type,
            entry.extracted_text,
            entry.description,
            entry.status,
            extra_fields_json,
            blocks_json,
            entry.image_filename
        ))
        conn.commit()
        return cursor.lastrowid

def get_entries(restaurant: t.Optional[str] = None, ticket_number: t.Optional[str] = None) -> t.List[sqlite3.Row]:
    """Get entries with optional filtering by restaurant and/or ticket number."""
    query = "SELECT * FROM entries WHERE 1=1"
    params = []

    if restaurant:
        query += " AND restaurant = ?"
        params.append(restaurant)

    if ticket_number:
        query += " AND ticket_number = ?"
        params.append(ticket_number)

    query += " ORDER BY created_at DESC"

    with get_db_connection() as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall()

def get_entry_by_id(entry_id: int) -> t.Optional[sqlite3.Row]:
    """Get a single entry by ID."""
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
        return cursor.fetchone()

def update_entry(entry_id: int, updates: t.Dict[str, t.Any]) -> bool:
    """Update an entry with the given fields."""
    if not updates:
        return False

    # Build the SET clause dynamically
    set_clauses = []
    params = []
    for key, value in updates.items():
        if key in ['restaurant', 'ticket_number', 'discrepancy_type', 'extracted_text', 'description', 'status', 'extra_fields', 'blocks', 'image_filename']:
            # Convert dict fields to JSON strings for storage
            if key in ('extra_fields', 'blocks') and value is not None:
                params.append(json.dumps(value))
            else:
                params.append(value)
            set_clauses.append(f"{key} = ?")

    if not set_clauses:
        return False

    # Always update the updated_at timestamp
    set_clauses.append("updated_at = CURRENT_TIMESTAMP")
    params.append(entry_id)

    query = f"UPDATE entries SET {', '.join(set_clauses)} WHERE id = ?"

    with get_db_connection() as conn:
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor.rowcount > 0

def delete_entry(entry_id: int) -> bool:
    """Delete an entry by ID."""
    with get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_ticket_record(ticket_id: str) -> t.Optional[sqlite3.Row]:
    """Return one merged ticket record by normalized Ticket ID."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM ticket_records WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()


def upsert_ticket_record(ticket: t.Dict[str, t.Any]) -> sqlite3.Row:
    """Insert or merge a ticket record atomically, preserving populated fields."""
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM ticket_records WHERE ticket_id = ?",
            (ticket["ticket_id"],),
        ).fetchone()

        if existing:
            def existing_json(name: str) -> t.Any:
                raw = existing[name]
                try:
                    return json.loads(raw) if raw else None
                except (json.JSONDecodeError, TypeError):
                    return None

            merged = dict(ticket)
            for field in (
                "restaurant", "phone", "ticket_date", "terminal", "table_name",
                "department", "user_name", "payment_status", "credit_card_amount",
                "ticket_total", "grand_total", "charged",
            ):
                merged[field] = ticket.get(field) or existing[field]

            old_extra = existing_json("extra_fields") or {}
            old_extra.update(ticket.get("extra_fields") or {})
            merged["extra_fields"] = old_extra

            old_items = existing_json("items") or []
            seen_items = {
                (
                    str(item.get("name", "")).strip().casefold(),
                    str(item.get("quantity", "")).strip(),
                    str(item.get("unit_price", "")).strip(),
                )
                for item in old_items
            }
            for item in ticket.get("items") or []:
                key = (
                    str(item.get("name", "")).strip().casefold(),
                    str(item.get("quantity", "")).strip(),
                    str(item.get("unit_price", "")).strip(),
                )
                if key not in seen_items:
                    old_items.append(item)
                    seen_items.add(key)
            merged["items"] = old_items

            old_screenshots = existing_json("screenshot_filenames") or []
            merged["screenshot_filenames"] = list(dict.fromkeys(
                old_screenshots + (ticket.get("screenshot_filenames") or [])
            ))
            old_raw_texts = existing_json("raw_texts") or []
            merged["raw_texts"] = list(dict.fromkeys(
                old_raw_texts + (ticket.get("raw_texts") or [])
            ))
            # Vision beats OCR fallback: one vision-parsed screenshot upgraded
            # the whole merged record.
            merged["extraction_method"] = (
                "vision"
                if ticket.get("extraction_method") == "vision" or existing["extraction_method"] == "vision"
                else ticket.get("extraction_method") or existing["extraction_method"]
            )

            conn.execute("""
                UPDATE ticket_records SET
                    ticket_id_display = ?, restaurant = ?, phone = ?, ticket_date = ?,
                    terminal = ?, table_name = ?, department = ?, user_name = ?,
                    payment_status = ?, credit_card_amount = ?, ticket_total = ?,
                    grand_total = ?, charged = ?, extra_fields = ?, items = ?,
                    screenshot_filenames = ?, raw_texts = ?, extraction_method = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE ticket_id = ?
            """, (
                merged.get("ticket_id_display") or existing["ticket_id_display"],
                merged.get("restaurant"), merged.get("phone"), merged.get("ticket_date"),
                merged.get("terminal"), merged.get("table_name"), merged.get("department"),
                merged.get("user_name"), merged.get("payment_status"),
                merged.get("credit_card_amount"), merged.get("ticket_total"),
                merged.get("grand_total"), merged.get("charged"),
                json.dumps(merged["extra_fields"]), json.dumps(merged["items"]),
                json.dumps(merged["screenshot_filenames"]), json.dumps(merged["raw_texts"]),
                merged["extraction_method"],
                ticket["ticket_id"],
            ))
        else:
            conn.execute("""
                INSERT INTO ticket_records (
                    ticket_id, ticket_id_display, restaurant, phone, ticket_date,
                    terminal, table_name, department, user_name, payment_status,
                    credit_card_amount, ticket_total, grand_total, charged,
                    extra_fields, items, screenshot_filenames, raw_texts,
                    extraction_method
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticket["ticket_id"], ticket["ticket_id_display"], ticket.get("restaurant"),
                ticket.get("phone"), ticket.get("ticket_date"), ticket.get("terminal"),
                ticket.get("table_name"), ticket.get("department"), ticket.get("user_name"),
                ticket.get("payment_status"), ticket.get("credit_card_amount"),
                ticket.get("ticket_total"), ticket.get("grand_total"), ticket.get("charged"),
                json.dumps(ticket.get("extra_fields") or {}),
                json.dumps(ticket.get("items") or []),
                json.dumps(ticket.get("screenshot_filenames") or []),
                json.dumps(ticket.get("raw_texts") or []),
                ticket.get("extraction_method"),
            ))

        items_for_child_table = merged["items"] if existing else (ticket.get("items") or [])
        conn.execute("DELETE FROM ticket_items WHERE ticket_id = ?", (ticket["ticket_id"],))
        conn.executemany(
            """
            INSERT INTO ticket_items (ticket_id, item, category, price, qty, total, is_void)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    ticket["ticket_id"], item.get("name"), item.get("category"),
                    item.get("price") or item.get("unit_price"),
                    item.get("qty") or item.get("quantity"), item.get("total"),
                    int(bool(item.get("is_void"))),
                )
                for item in items_for_child_table
            ],
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM ticket_records WHERE ticket_id = ?",
            (ticket["ticket_id"],),
        ).fetchone()


def create_docket_record(docket: t.Dict[str, t.Any]) -> int:
    """Persist one parsed docket; docket order numbers are intentionally not unique."""
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO docket_records (
                docket_order_no, docket_date, docket_time, item, discrepancy_type,
                handwritten_reason, printed_text, raw_text, extra_fields,
                image_filename, review_required, review_reason, extraction_method
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            docket.get("docket_order_no"), docket.get("docket_date"),
            docket.get("docket_time"), docket.get("item"),
            docket.get("discrepancy_type"), docket.get("handwritten_reason"),
            docket.get("printed_text") or "", docket.get("raw_text") or "",
            json.dumps(docket.get("extra_fields") or {}), docket["image_filename"],
            int(bool(docket.get("review_required"))), docket.get("review_reason"),
            docket.get("extraction_method"),
        ))
        conn.commit()
        return cursor.lastrowid


def get_docket_record(docket_id: int) -> t.Optional[sqlite3.Row]:
    """Return a docket row after it has been persisted."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM docket_records WHERE id = ?",
            (docket_id,),
        ).fetchone()


def get_ticket_records() -> t.List[sqlite3.Row]:
    """Return all merged ticket records in stable update order."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM ticket_records ORDER BY updated_at DESC, ticket_id"
        ).fetchall()


def get_ticket_items(ticket_id: str) -> t.List[sqlite3.Row]:
    """Return normalized child item rows for one ticket."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT item, category, price, qty, total, is_void FROM ticket_items WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()


def get_docket_records() -> t.List[sqlite3.Row]:
    """Return all docket records in stable creation order."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM docket_records ORDER BY created_at ASC, id ASC"
        ).fetchall()


def upsert_sales_report(report: t.Dict[str, t.Any]) -> sqlite3.Row:
    """One report row per branch + date; a re-upload replaces the previous one.

    `departments` is the long slip (Source 1). `excel_rows` is the row-level
    Daily Exception log (Source 2) and is fully replaced with the report, so a
    re-upload can never leave stale exception rows behind.
    """
    restaurant = str(report.get("restaurant") or "").strip()
    report_date = report.get("report_date")
    date_key = canonical_date_key(report_date)

    with get_db_connection() as conn:
        existing = None
        if restaurant:
            for row in conn.execute(
                "SELECT * FROM sales_reports WHERE restaurant = ?", (restaurant,)
            ).fetchall():
                raw = row["report_date"]
                other = canonical_date_key(raw)
                if raw == report_date or (date_key and other == date_key) or (not raw and not report_date):
                    existing = row
                    break

        values = (
            report_date,
            json.dumps(report.get("departments") or []),
            report.get("source") or "image",
            int(bool(report.get("cross_verified"))),
            report.get("confirmed_source"),
            report.get("image_filename"),
            report.get("excel_filename"),
            report.get("extracted_text") or "",
            report.get("extraction_method"),
            json.dumps(report.get("extra_fields") or {}),
            json.dumps(report.get("excel_summary") or {}),
            int(report.get("excel_skipped_rows") or 0),
            int(report.get("excel_void_rows") or 0),
            int(report.get("excel_unfilled_rows") or 0),
        )

        if existing:
            conn.execute("""
                UPDATE sales_reports SET
                    report_date = ?, departments = ?, source = ?,
                    cross_verified = ?, confirmed_source = ?, image_filename = ?,
                    excel_filename = ?, extracted_text = ?, extraction_method = ?,
                    extra_fields = ?, excel_summary = ?, excel_skipped_rows = ?,
                    excel_void_rows = ?, excel_unfilled_rows = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, values + (existing["id"],))
            report_id = existing["id"]
        else:
            cursor = conn.execute("""
                INSERT INTO sales_reports (
                    restaurant, report_date, departments, source, cross_verified,
                    confirmed_source, image_filename, excel_filename, extracted_text,
                    extraction_method, extra_fields, excel_summary, excel_skipped_rows,
                    excel_void_rows, excel_unfilled_rows
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (restaurant,) + values)
            report_id = cursor.lastrowid

        # Source 2 rows are replaced wholesale with the report.
        conn.execute("DELETE FROM daily_exception_rows WHERE report_id = ?", (report_id,))
        for row in report.get("excel_rows") or []:
            conn.execute("""
                INSERT INTO daily_exception_rows (
                    report_id, row_date, branch, bill_number, item, quantity, amount,
                    adjustment_type, adjustment, food_status, payment_status,
                    cashier_name, approving_manager, reason, posted_in_group_chat,
                    docket_photo_attached, proof, audit_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report_id, row.get("date"), row.get("branch"), row.get("bill_number"),
                row.get("item"), row.get("quantity"), row.get("amount"),
                row.get("adjustment_type"), row.get("adjustment"), row.get("food_status"),
                row.get("payment_status"), row.get("cashier_name"),
                row.get("approving_manager"), row.get("reason"),
                row.get("posted_in_group_chat"), row.get("docket_photo_attached"),
                row.get("proof"), row.get("audit_status"),
            ))

        saved = conn.execute(
            "SELECT * FROM sales_reports WHERE id = ?", (report_id,)
        ).fetchone()
        conn.commit()
        return saved


def get_sales_reports() -> t.List[sqlite3.Row]:
    """Return all stored sales reports, newest first."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM sales_reports ORDER BY updated_at DESC, created_at DESC, id DESC"
        ).fetchall()


def get_sales_report_by_id(report_id: int) -> t.Optional[sqlite3.Row]:
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM sales_reports WHERE id = ?", (report_id,)
        ).fetchone()


def get_daily_exception_rows(report_id: int) -> t.List[sqlite3.Row]:
    """The stored Excel Daily Exception log for one report, in file order."""
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT * FROM daily_exception_rows WHERE report_id = ? ORDER BY id ASC",
            (report_id,),
        ).fetchall()
