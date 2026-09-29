import json
import os
import re
import sqlite3
from contextlib import contextmanager
from typing import Any

DATABASE_PATH = "./data/til_system.db"


@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    with get_db_connection() as conn:
        # The former bill-slip records are obsolete and intentionally cleared.
        conn.execute("DROP TABLE IF EXISTS entries")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS ticket_records (
            ticket_id TEXT PRIMARY KEY, ticket_id_display TEXT NOT NULL, restaurant TEXT,
            phone TEXT, selected_branch TEXT, ticket_date TEXT, terminal TEXT, table_name TEXT, department TEXT,
            user_name TEXT, payment_status TEXT, credit_card_amount TEXT, ticket_total TEXT,
            grand_total TEXT, charged TEXT, extra_fields TEXT, items TEXT NOT NULL,
            screenshot_filenames TEXT NOT NULL, raw_texts TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ticket_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL REFERENCES ticket_records(ticket_id) ON DELETE CASCADE,
            item TEXT, modifier TEXT, category TEXT, price TEXT, qty TEXT, total TEXT, is_void INTEGER NOT NULL DEFAULT 0,
            row_tint INTEGER NOT NULL DEFAULT 0, strikethrough_line INTEGER NOT NULL DEFAULT 0,
            void_label_text INTEGER NOT NULL DEFAULT 0, void_confidence TEXT, review_flags TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS docket_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, docket_order_no TEXT, docket_date TEXT, docket_time TEXT,
            department TEXT, selected_branch TEXT, table_name TEXT, covers TEXT, item TEXT, discrepancy_type TEXT, handwritten_reason TEXT, printed_text TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL DEFAULT '', extra_fields TEXT, image_filename TEXT NOT NULL,
            review_required INTEGER NOT NULL DEFAULT 0, review_reason TEXT, staff_name TEXT,
            description_confidence REAL, multiple_dockets INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS csv_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT, branch TEXT NOT NULL, selected_date TEXT NOT NULL,
            row_date TEXT, product TEXT, quantity REAL, user_name TEXT, department TEXT, till TEXT,
            category TEXT, group_name TEXT, sales_value REAL, void_count REAL NOT NULL DEFAULT 0,
            cancel_count REAL NOT NULL DEFAULT 0, promotion_count REAL NOT NULL DEFAULT 0, raw_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS upload_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, filename TEXT NOT NULL,
            raw_json TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS csv_imports (
            branch TEXT NOT NULL, selected_date TEXT NOT NULL, filename TEXT,
            promotions_in_file INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(branch, selected_date)
        );
        CREATE TABLE IF NOT EXISTS unassigned_screenshots (
            filename TEXT PRIMARY KEY, file_hash TEXT NOT NULL, selected_branch TEXT, selected_date TEXT,
            parsed_json TEXT NOT NULL, issue TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS upload_hashes (
            kind TEXT NOT NULL, file_hash TEXT NOT NULL, filename TEXT NOT NULL,
            record_id INTEGER, PRIMARY KEY(kind,file_hash)
        );
        CREATE TABLE IF NOT EXISTS extraction_jobs (
            job_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, kind TEXT NOT NULL,
            original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL,
            file_hash TEXT NOT NULL, branch TEXT NOT NULL, selected_date TEXT NOT NULL,
            status TEXT NOT NULL, message TEXT, provider TEXT, error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # Additive migration for installations created by the previous ticket/docket workflow.
        for stmt in (
            "ALTER TABLE ticket_items ADD COLUMN modifier TEXT",
            "ALTER TABLE ticket_items ADD COLUMN row_tint INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE ticket_items ADD COLUMN strikethrough_line INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE ticket_items ADD COLUMN void_label_text INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE ticket_items ADD COLUMN void_confidence TEXT",
            "ALTER TABLE ticket_items ADD COLUMN review_flags TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE ticket_records ADD COLUMN selected_branch TEXT",
            "ALTER TABLE ticket_records ADD COLUMN screenshot_segments TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE ticket_records ADD COLUMN review_flags TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE docket_records ADD COLUMN staff_name TEXT",
            "ALTER TABLE docket_records ADD COLUMN department TEXT",
            "ALTER TABLE docket_records ADD COLUMN selected_branch TEXT",
            "ALTER TABLE docket_records ADD COLUMN table_name TEXT",
            "ALTER TABLE docket_records ADD COLUMN covers TEXT",
            "ALTER TABLE docket_records ADD COLUMN description_confidence REAL",
            "ALTER TABLE docket_records ADD COLUMN multiple_dockets INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE docket_records ADD COLUMN item_lines TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE docket_records ADD COLUMN item_views TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE docket_records ADD COLUMN image_filenames TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE docket_records ADD COLUMN field_conflicts TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE docket_records ADD COLUMN partial_fields TEXT NOT NULL DEFAULT '[]'",
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        conn.commit()


def get_ticket_record(ticket_id: str):
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM ticket_records WHERE ticket_id=?", (ticket_id,)).fetchone()


def upsert_ticket_record(ticket: dict[str, Any]):
    with get_db_connection() as conn:
        existing = conn.execute("SELECT * FROM ticket_records WHERE ticket_id=?", (ticket["ticket_id"],)).fetchone()
        if existing:
            merged = dict(ticket)
            for key in ("restaurant", "phone", "selected_branch", "ticket_date", "terminal", "table_name", "department", "user_name", "payment_status", "credit_card_amount"):
                merged[key] = ticket.get(key) or existing[key]
            old_extra = json.loads(existing["extra_fields"] or "{}")
            old_extra.update(ticket.get("extra_fields") or {})
            merged["extra_fields"] = old_extra
            for field in ("screenshot_filenames", "raw_texts"):
                merged[field] = list(dict.fromkeys(json.loads(existing[field] or "[]") + ticket.get(field, [])))
            segments = json.loads(existing["screenshot_segments"] or "[]")
            if not segments and json.loads(existing["items"] or "[]"):
                segments = [{"filename": "legacy", "file_hash": "legacy", "items": json.loads(existing["items"] or "[]")}]
            incoming_segments = ticket.get("screenshot_segments") or []
            if any(segment.get("items") for segment in incoming_segments):
                replacement_hashes = {segment.get("file_hash") for segment in incoming_segments if segment.get("file_hash")}
                replacement_names = {segment.get("filename") for segment in incoming_segments if segment.get("filename")}
                segments = [
                    segment for segment in segments
                    if segment.get("file_hash") not in replacement_hashes
                    and segment.get("filename") not in replacement_names
                ]
            segments.extend(incoming_segments)
            merged["screenshot_segments"] = segments
            merged["items"], gap = _merge_ticket_segments(segments)
            flags = json.loads(existing["review_flags"] or "[]")
            flags = [flag for flag in flags if not flag.startswith("possible gap:") and flag != "items may be missing"]
            old_totals = {k: existing[k] for k in ("ticket_total", "grand_total", "charged")}
            for key in old_totals:
                incoming = ticket.get(key)
                if old_totals[key] and incoming and _money(old_totals[key]) != _money(incoming):
                    flags.append(f"conflicting {key}: {old_totals[key]} vs {incoming}")
                merged[key] = old_totals[key] or incoming
            if gap:
                flags.append("possible gap: a screenshot may be missing")
            total = _money(merged.get("ticket_total"))
            item_amounts = [_money(i.get("total")) for i in merged.get("items", []) if not i.get("is_void")]
            if total is not None and item_amounts and all(value is not None for value in item_amounts) and round(sum(item_amounts), 2) != total:
                flags.append("items may be missing")
            merged["review_flags"] = list(dict.fromkeys(flags))
        else:
            merged = ticket
            merged.setdefault("screenshot_segments", ticket.get("screenshot_segments") or [])
            merged.setdefault("review_flags", [])
            merged.setdefault("items", [item for segment in merged["screenshot_segments"] for item in segment.get("items", [])])
            merged.setdefault("screenshot_filenames", ticket.get("screenshot_filenames", []))
            merged.setdefault("raw_texts", ticket.get("raw_texts", []))
            if existing is None:
                merged["items"], gap = _merge_ticket_segments(merged["screenshot_segments"])
                if gap:
                    merged["review_flags"].append("possible gap: a screenshot may be missing")
            flags = merged["review_flags"]
            total = _money(merged.get("ticket_total"))
            amounts = [_money(i.get("total")) for i in merged["items"] if not i.get("is_void")]
            if total is not None and amounts and all(v is not None for v in amounts) and round(sum(amounts), 2) != total:
                flags.append("items may be missing")
            merged["review_flags"] = list(dict.fromkeys(flags))
        conn.execute("""INSERT OR REPLACE INTO ticket_records(ticket_id,ticket_id_display,restaurant,phone,selected_branch,ticket_date,terminal,table_name,department,user_name,payment_status,credit_card_amount,ticket_total,grand_total,charged,extra_fields,items,screenshot_filenames,raw_texts,screenshot_segments,review_flags,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""", (
            merged["ticket_id"], merged.get("ticket_id_display") or f"#{merged['ticket_id']}", merged.get("restaurant"), merged.get("phone"), merged.get("selected_branch"), merged.get("ticket_date"), merged.get("terminal"), merged.get("table_name"), merged.get("department"), merged.get("user_name"), merged.get("payment_status"), merged.get("credit_card_amount"), merged.get("ticket_total"), merged.get("grand_total"), merged.get("charged"), json.dumps(merged.get("extra_fields") or {}), json.dumps(merged.get("items") or []), json.dumps(merged.get("screenshot_filenames") or []), json.dumps(merged.get("raw_texts") or []), json.dumps(merged.get("screenshot_segments") or []), json.dumps(merged.get("review_flags") or [])))
        conn.execute("DELETE FROM ticket_items WHERE ticket_id=?", (ticket["ticket_id"],))
        conn.executemany("""INSERT INTO ticket_items(ticket_id,item,modifier,category,price,qty,total,is_void,row_tint,strikethrough_line,void_label_text,void_confidence,review_flags)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
            (
                ticket["ticket_id"], i.get("name"), i.get("modifier"), i.get("category"),
                i.get("price") or i.get("unit_price"), i.get("qty") or i.get("quantity"), i.get("total"),
                int(bool(i.get("is_void"))),
                int(bool((i.get("signals") or {}).get("row_tint"))),
                int(bool((i.get("signals") or {}).get("strikethrough_line", (i.get("signals") or {}).get("strikethrough")))),
                int(bool((i.get("signals") or {}).get("void_label_text", (i.get("signals") or {}).get("label")))),
                i.get("void_confidence"), json.dumps(i.get("review_flags") or []),
            ) for i in merged.get("items", [])
        ])
        conn.commit()
        return conn.execute("SELECT * FROM ticket_records WHERE ticket_id=?", (ticket["ticket_id"],)).fetchone()


def create_docket_record(docket: dict[str, Any]) -> int:
    with get_db_connection() as conn:
        candidates = conn.execute("SELECT * FROM docket_records WHERE selected_branch=?", (docket.get("selected_branch"),)).fetchall()
        new_items = docket.get("item_lines") or []
        new_voids = {_docket_item_fingerprint(i) for i in new_items if i.get("is_void") or i.get("marker_type")}
        existing = None
        for candidate in candidates:
            candidate_images = json.loads(candidate["image_filenames"] or "[]")
            same_key = bool(candidate["docket_date"] and docket.get("docket_date") and candidate["docket_order_no"] and docket.get("docket_order_no") and candidate["docket_date"] == docket.get("docket_date") and candidate["docket_order_no"] == docket.get("docket_order_no") and (candidate["docket_time"] or "") == (docket.get("docket_time") or ""))
            same_source_identity = docket.get("image_filename") in candidate_images and (
                not candidate["docket_order_no"] or not docket.get("docket_order_no")
                or candidate["docket_order_no"] == docket.get("docket_order_no")
            )
            if not same_key and not same_source_identity:
                continue
            prior_items = json.loads(candidate["item_lines"] or "[]")
            prior_voids = {_docket_item_fingerprint(i) for i in prior_items if i.get("is_void") or i.get("marker_type")}
            if prior_voids == new_voids or not prior_voids or not new_voids or prior_voids.issubset(new_voids) or new_voids.issubset(prior_voids):
                existing = candidate
                break
        conflicts = json.loads(existing["field_conflicts"] or "[]") if existing else []
        partials = json.loads(existing["partial_fields"] or "[]") if existing else []
        images = json.loads(existing["image_filenames"] or "[]") if existing else []
        prior_items = json.loads(existing["item_lines"] or "[]") if existing else []
        item_views = json.loads(existing["item_views"] or "[]") if existing else []
        incoming_fields = dict(docket)
        for field in ("docket_order_no", "docket_date", "docket_time", "department", "table", "covers", "staff_name", "discrepancy_type", "handwritten_reason"):
            db_field = "table_name" if field == "table" else field
            old_value = existing[db_field] if existing and db_field in existing.keys() else None
            incoming = docket.get(field)
            if old_value and incoming and str(old_value).strip().casefold() != str(incoming).strip().casefold():
                conflicts.append({"field": field, "values": list(dict.fromkeys([old_value, incoming]))})
            docket[field] = old_value or incoming
        if existing and not docket.get("table"):
            docket["table"] = existing["table_name"]
        if existing and not docket.get("description_confidence"):
            docket["description_confidence"] = existing["description_confidence"]
        completed_fields = {name for name in ("docket_order_no", "docket_date", "docket_time", "department", "table", "covers", "staff_name", "handwritten_reason") if incoming_fields.get(name)}
        partials = [field for field in partials if field not in completed_fields]
        if new_items:
            item_views.append({"filename": docket.get("image_filename", ""), "items": new_items})
            prior_items, _ = _merge_ticket_segments(item_views)
        if docket.get("partial_fields"):
            partials = list(dict.fromkeys(partials + docket["partial_fields"]))
        if docket.get("image_filename"):
            images.append(docket["image_filename"])
        images = list(dict.fromkeys(images))
        review = bool(docket.get("review_required") or conflicts)
        reason = "Conflicting readings: " + ", ".join(dict.fromkeys(c["field"] for c in conflicts)) if conflicts else docket.get("review_reason")
        discrepancy_items = [i for i in prior_items if i.get("is_void") or i.get("marker_type")]
        docket["item"] = "; ".join(i.get("name") or "" for i in discrepancy_items) or docket.get("item")
        docket["item_lines"] = prior_items
        docket["image_filenames"] = images
        docket["field_conflicts"] = conflicts
        docket["partial_fields"] = partials
        docket["review_required"] = review
        docket["review_reason"] = reason
        docket["image_filename"] = images[0] if images else docket["image_filename"]
        if existing:
            conn.execute("""UPDATE docket_records SET docket_order_no=?,docket_date=?,docket_time=?,department=?,table_name=?,covers=?,item=?,discrepancy_type=?,handwritten_reason=?,extra_fields=?,image_filename=?,image_filenames=?,staff_name=?,description_confidence=?,multiple_dockets=?,item_lines=?,item_views=?,field_conflicts=?,partial_fields=?,review_required=?,review_reason=? WHERE id=?""", (docket.get("docket_order_no"), docket.get("docket_date"), docket.get("docket_time"), docket.get("department"), docket.get("table"), docket.get("covers"), docket.get("item"), docket.get("discrepancy_type"), docket.get("handwritten_reason"), json.dumps(docket.get("extra_fields") or {}), docket["image_filename"], json.dumps(images), docket.get("staff_name"), docket.get("description_confidence"), int(bool(docket.get("multiple_dockets"))), json.dumps(prior_items), json.dumps(item_views), json.dumps(conflicts), json.dumps(partials), int(bool(review or partials)), reason, existing["id"]))
            record_id = existing["id"]
        else:
            cur = conn.execute("""INSERT INTO docket_records(docket_order_no,docket_date,docket_time,department,selected_branch,table_name,covers,item,discrepancy_type,handwritten_reason,printed_text,raw_text,extra_fields,image_filename,image_filenames,item_lines,item_views,field_conflicts,partial_fields,review_required,review_reason,staff_name,description_confidence,multiple_dockets)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (docket.get("docket_order_no"), docket.get("docket_date"), docket.get("docket_time"), docket.get("department"), docket.get("selected_branch"), docket.get("table"), docket.get("covers"), docket.get("item"), docket.get("discrepancy_type"), docket.get("handwritten_reason"), docket.get("printed_text") or "", docket.get("raw_text") or "", json.dumps(docket.get("extra_fields") or {}), docket["image_filename"], json.dumps(images), json.dumps(prior_items), json.dumps(item_views), json.dumps(conflicts), json.dumps(partials), int(bool(review or partials)), reason, docket.get("staff_name"), docket.get("description_confidence"), int(bool(docket.get("multiple_dockets")))))
            record_id = cur.lastrowid
        conn.commit()
        return record_id


def get_docket_record(docket_id: int):
    with get_db_connection() as conn:
        return conn.execute("SELECT * FROM docket_records WHERE id=?", (docket_id,)).fetchone()


def _money(value):
    try:
        return round(float(str(value).replace("£", "").replace(",", "").strip()), 2)
    except (ValueError, TypeError):
        return None


def _item_fingerprint(item):
    name = re.sub(r"\s*\(void\)\s*$", "", str(item.get("name") or ""), flags=re.I).casefold().strip()
    modifier = item.get("modifier") or " ".join(item.get("modifiers") or [])
    price = item.get("price") or item.get("unit_price") or ""
    return (name, str(price).strip(), str(item.get("quantity") or item.get("qty") or "").strip(), str(item.get("total") or "").strip(), str(modifier).casefold().strip(), bool(item.get("is_void")), str(item.get("marker_type") or "").casefold())


def _docket_item_fingerprint(item):
    name = re.sub(r"\s*\(void\)\s*$", "", str(item.get("name") or ""), flags=re.I).casefold().strip()
    return (name, str(item.get("quantity") or item.get("qty") or "").strip(), str(item.get("total") or "").strip(), bool(item.get("is_void")), str(item.get("marker_type") or "").casefold())


def _merge_ticket_segments(segments):
    segments = [s for s in segments if s.get("items")]
    unique = []
    seen_sequences = set()
    for segment in segments:
        sequence = tuple(_item_fingerprint(item) for item in segment["items"])
        if sequence not in seen_sequences:
            seen_sequences.add(sequence)
            unique.append(segment)
    segments = unique
    if len(segments) < 2:
        return (segments[0]["items"] if segments else []), False
    edges = {}
    incoming = {i: 0 for i in range(len(segments))}
    for i, left in enumerate(segments):
        for j, right in enumerate(segments):
            if i == j:
                continue
            a, b = left["items"], right["items"]
            overlap = 0
            for size in range(1, min(len(a), len(b)) + 1):
                if [_item_fingerprint(x) for x in a[-size:]] == [_item_fingerprint(x) for x in b[:size]]:
                    overlap = size
            if overlap:
                edges[(i, j)] = overlap
                incoming[j] += 1
    starts = [i for i, count in incoming.items() if count == 0]
    if len(starts) != 1:
        return [item for segment in sorted(segments, key=lambda s: s.get("filename", "")) for item in segment["items"]], True
    order, used, current = [], set(), starts[0]
    while current not in used:
        order.append(current); used.add(current)
        next_nodes = [j for i, j in edges if i == current and j not in used]
        if len(next_nodes) > 1:
            return [item for segment in sorted(segments, key=lambda s: s.get("filename", "")) for item in segment["items"]], True
        if not next_nodes:
            break
        current = next_nodes[0]
    if len(used) != len(segments):
        return [item for segment in sorted(segments, key=lambda s: s.get("filename", "")) for item in segment["items"]], True
    merged = list(segments[order[0]]["items"])
    for previous, current in zip(order, order[1:]):
        overlap = edges[(previous, current)]
        merged.extend(segments[current]["items"][overlap:])
    return merged, False
