import hashlib
import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.verification import build_verification
from app.extraction.gemini import VisionExtractionError, extract_image as extract_gemini_image
from app.extraction.ticket_ocr import extract_ticket as extract_ticket_ocr
from app.storage.db import (
    create_docket_record,
    get_db_connection,
    get_docket_record,
    get_ticket_record,
    upsert_ticket_record,
)

router = APIRouter()
ROOT = "data/uploads"
TICKET_DIR = os.path.join(ROOT, "ticket_screenshots")
DOCKET_DIR = os.path.join(ROOT, "dockets")
os.makedirs(TICKET_DIR, exist_ok=True)
os.makedirs(DOCKET_DIR, exist_ok=True)
MAX_FILES = 30
TICKET_ID_RE = re.compile(r"^\d{6}-\d+$")
log = logging.getLogger(__name__)
_job_queue: asyncio.Queue[str] | None = None
_worker_tasks: list[asyncio.Task] = []


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _add_audit(kind: str, filename: str, raw: str):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO upload_audits(kind,filename,raw_json) VALUES(?,?,?)", (kind, filename, raw or ""))
        conn.commit()


def _duplicate(kind: str, file_hash: str):
    with get_db_connection() as conn:
        return conn.execute("SELECT filename FROM upload_hashes WHERE kind=? AND file_hash=?", (kind, file_hash)).fetchone()


def _remember_hash(kind: str, file_hash: str, filename: str, record_id: int | None = None):
    with get_db_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO upload_hashes(kind,file_hash,filename,record_id) VALUES(?,?,?,?)", (kind, file_hash, filename, record_id))
        conn.commit()


def _forget_hash(kind: str, file_hash: str):
    with get_db_connection() as conn:
        conn.execute('DELETE FROM upload_hashes WHERE kind=? AND file_hash=?', (kind, file_hash))
        conn.commit()


def _ticket_storage(parsed: dict[str, Any], filename: str, file_hash: str, branch: str, raw_text: str = ""):
    ticket_id = str(parsed.get("ticket_id") or "").strip().lstrip("#")
    if not TICKET_ID_RE.fullmatch(ticket_id):
        raise ValueError("Ticket ID is missing or invalid; it must match YYMMDD-N")
    items = []
    for source in parsed.get("items", []):
        item = dict(source)
        item["quantity"] = item.get("qty")
        item["unit_price"] = item.get("price")
        item.setdefault("is_void", False)
        items.append(item)
    return {
        "ticket_id": ticket_id,
        "ticket_id_display": f"#{ticket_id}",
        "restaurant": parsed.get("branch"),
        "selected_branch": branch,
        "phone": None,
        "ticket_date": parsed.get("date"),
        "terminal": parsed.get("terminal"),
        "table_name": parsed.get("table"),
        "department": parsed.get("department"),
        "user_name": parsed.get("user"),
        "payment_status": parsed.get("payment_status"),
        "credit_card_amount": parsed.get("credit_card"),
        "ticket_total": parsed.get("ticket_total"),
        "grand_total": parsed.get("grand_total"),
        "charged": parsed.get("charged"),
        "extra_fields": _extra_fields_dict(parsed.get("extra_fields")),
        "items": items,
        "screenshot_filenames": [filename],
        "raw_texts": _ticket_texts(raw_text),
        "screenshot_segments": [{"filename": filename, "file_hash": file_hash, "items": items}],
    }


def _ticket_texts(raw: str) -> list[str]:
    """Keep each OCR text pass in the ticket record's raw_texts column."""
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return [raw]
    if isinstance(decoded, dict):
        texts = [decoded.get("original_text"), decoded.get("line_cleaned_text")]
        return list(dict.fromkeys(text for text in texts if isinstance(text, str) and text.strip())) or [raw]
    return [raw]


def _extra_fields_dict(value: Any) -> dict[str, Any]:
    """Normalize OCR's list of labeled fields to the ticket table's key/value map."""
    if isinstance(value, dict):
        return value
    result = {}
    if isinstance(value, list):
        for field in value:
            if isinstance(field, dict):
                key = field.get("key") or field.get("name") or field.get("label")
                val = field.get("value")
                if key and val is not None:
                    result[str(key)] = val
    return result


def _save_unassigned(filename: str, file_hash: str, branch: str, selected_date: str, parsed: dict[str, Any], issue: str):
    with get_db_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO unassigned_screenshots(filename,file_hash,selected_branch,selected_date,parsed_json,issue) VALUES(?,?,?,?,?,?)", (filename, file_hash, branch, selected_date, json.dumps(parsed, ensure_ascii=False), issue))
        conn.commit()
    _remember_hash("ticket", file_hash, filename)


def _job_update(job_id: str, status: str, message: str = '', provider: str | None = None, error: str | None = None):
    with get_db_connection() as conn:
        conn.execute('UPDATE extraction_jobs SET status=?,message=?,provider=COALESCE(?,provider),error=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?', (status, message, provider, error, job_id))
        conn.commit()


def _job_row(job_id: str):
    with get_db_connection() as conn:
        row = conn.execute('SELECT * FROM extraction_jobs WHERE job_id=?', (job_id,)).fetchone()
        return dict(row) if row else None


def _save_extracted_job(job: dict[str, Any]):
    kind = job['kind']
    directory = TICKET_DIR if kind == 'ticket' else DOCKET_DIR
    path = os.path.join(directory, job['stored_filename'])
    if kind == 'ticket':
        parsed, raw = extract_ticket_ocr(path)
        provider = 'tesseract_ocr'
        _add_audit('ticket:tesseract', job['stored_filename'], raw)
    else:
        try:
            parsed, raw = extract_gemini_image(path, kind)
            provider = 'gemini'
            _add_audit(f'{kind}:gemini', job['stored_filename'], raw)
        except VisionExtractionError as gemini_error:
            _add_audit(f'{kind}:gemini', job['stored_filename'], gemini_error.raw_json)
            raise RuntimeError(f'Gemini docket extraction failed: {gemini_error}') from gemini_error

    if kind == 'ticket':
        ticket_id = str(parsed.get('ticket_id') or '').strip().lstrip('#')
        issues = []
        if not TICKET_ID_RE.fullmatch(ticket_id):
            issues.append('Ticket ID unreadable or invalid; enter the ID to assign this screenshot')
        if parsed.get('branch') and _norm(parsed['branch']) != _norm(job['branch']):
            issues.append(f'Ticket branch mismatch: image says {parsed["branch"]}')
        if TICKET_ID_RE.fullmatch(ticket_id) and ticket_id[:6] != job['selected_date'].replace('-', '')[2:8]:
            issues.append(f'Ticket date mismatch: ID belongs to 20{ticket_id[:2]}-{ticket_id[2:4]}-{ticket_id[4:6]}')
        if issues:
            _save_unassigned(job['stored_filename'], job['file_hash'], job['branch'], job['selected_date'], parsed, '; '.join(issues))
            message = 'Needs confirmation: ' + '; '.join(issues)
        else:
            mapped = _ticket_storage(parsed, job['stored_filename'], job['file_hash'], job['branch'], raw)
            record = upsert_ticket_record(mapped)
            if get_ticket_record(record['ticket_id']) is None:
                raise RuntimeError('Ticket row was not readable after saving')
            _remember_hash(kind, job['file_hash'], job['stored_filename'])
            message = f'Saved ticket {record["ticket_id"]}'
    else:
        views = parsed.get('dockets') or []
        if not views:
            raise ValueError('Vision extraction returned no structured docket views')
        saved_ids = []
        for view in views:
            raw_order = str(view.get('order_number') or '')
            match = re.search(r'(\d+)\s*$', raw_order)
            order = match.group(1) if match else None
            item_lines = view.get('items') or []
            marked = [item for item in item_lines if item.get('is_void') or item.get('marker_type')]
            discrepancy_type = next((item.get('marker_type') for item in marked if item.get('marker_type')), None)
            docket = {
                'docket_order_no': order, 'docket_date': view.get('date'), 'docket_time': view.get('time'),
                'department': view.get('department'), 'table': view.get('table'), 'covers': view.get('covers'),
                'selected_branch': job['branch'], 'staff_name': view.get('staff_name'),
                'item': '; '.join(item.get('name') or '' for item in marked) or None,
                'item_lines': item_lines, 'discrepancy_type': discrepancy_type,
                'handwritten_reason': view.get('description'), 'description_confidence': view.get('description_confidence'),
                'partial_fields': view.get('partial_fields') or [], 'extra_fields': view.get('extra_fields') or [],
                'image_filename': job['stored_filename'], 'raw_text': raw,
                'review_required': bool(view.get('partial_fields')),
                'review_reason': 'Partly cropped fields: ' + ', '.join(view['partial_fields']) if view.get('partial_fields') else None,
                'multiple_dockets': len(views) > 1,
            }
            docket_id = create_docket_record(docket)
            if get_docket_record(docket_id) is None:
                raise RuntimeError('Docket row was not readable after saving')
            saved_ids.append(docket_id)
        _remember_hash(kind, job['file_hash'], job['stored_filename'], saved_ids[0] if saved_ids else None)
        message = f'Saved {len(saved_ids)} docket view(s)'

    build_verification(job['branch'], job['selected_date'])
    return provider, message


async def _worker():
    assert _job_queue is not None
    while True:
        job_id = await _job_queue.get()
        try:
            job = _job_row(job_id)
            if not job or job['status'] == 'done':
                continue
            _job_update(job_id, 'processing', 'Processing image')
            try:
                provider, message = await asyncio.to_thread(_save_extracted_job, job)
                _job_update(job_id, 'done', message, provider=provider)
            except Exception as exc:
                log.exception('Vision extraction failed for %s', job['original_filename'])
                _forget_hash(job['kind'], job['file_hash'])
                failed_provider = 'gemini' if job['kind'] == 'docket' else 'tesseract_ocr'
                _job_update(job_id, 'failed', 'Extraction failed', provider=failed_provider, error=str(exc))
        finally:
            _job_queue.task_done()


async def start_extraction_workers():
    global _job_queue, _worker_tasks
    if _job_queue is not None:
        return
    _job_queue = asyncio.Queue()
    try:
        count = max(1, min(8, int(os.getenv('EXTRACTION_CONCURRENCY', '2'))))
    except ValueError:
        count = 2
    with get_db_connection() as conn:
        conn.execute("UPDATE extraction_jobs SET status='queued',message='Queued after server restart',updated_at=CURRENT_TIMESTAMP WHERE status='processing'")
        conn.execute("""UPDATE extraction_jobs SET status='queued',message='Retrying failed docket with Gemini',error=NULL,updated_at=CURRENT_TIMESTAMP
            WHERE kind='docket' AND status='failed' AND provider IS NULL AND stored_filename<>''""")
        queued = conn.execute("SELECT job_id FROM extraction_jobs WHERE status='queued' ORDER BY created_at").fetchall()
    for row in queued:
        _job_queue.put_nowait(row['job_id'])
    _worker_tasks = [asyncio.create_task(_worker(), name=f'extraction-worker-{i + 1}') for i in range(count)]


async def stop_extraction_workers():
    global _job_queue, _worker_tasks
    for task in _worker_tasks:
        task.cancel()
    if _worker_tasks:
        await asyncio.gather(*_worker_tasks, return_exceptions=True)
    _worker_tasks = []
    _job_queue = None


async def _batch(files: list[UploadFile], kind: str, branch: str, selected_date: str):
    if len(files) > MAX_FILES:
        raise HTTPException(400, f'Upload accepts at most {MAX_FILES} images')
    if _job_queue is None:
        await start_extraction_workers()
    batch_id = str(uuid.uuid4())
    batch_jobs = []
    for upload in files:
        original = upload.filename or 'upload.png'
        job_id = str(uuid.uuid4())
        if not upload.content_type or not upload.content_type.startswith('image/'):
            with get_db_connection() as conn:
                conn.execute('INSERT INTO extraction_jobs(job_id,batch_id,kind,original_filename,stored_filename,file_hash,branch,selected_date,status,message,error) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                             (job_id, batch_id, kind, original, '', '', branch, selected_date, 'failed', 'Upload rejected', 'File must be an image'))
                conn.commit()
            batch_jobs.append({'job_id': None, 'filename': original, 'status': 'failed', 'message': 'File must be an image'})
            continue
        contents = await upload.read()
        file_hash = hashlib.sha256(contents).hexdigest()
        duplicate = _duplicate(kind, file_hash)
        if duplicate:
            stored = duplicate['filename']
            status, message = 'done', 'Duplicate, skipped'
        else:
            stored = f'{kind}-{uuid.uuid4()}{os.path.splitext(original)[1] or ".jpg"}'
            directory = TICKET_DIR if kind == 'ticket' else DOCKET_DIR
            with open(os.path.join(directory, stored), 'wb') as output:
                output.write(contents)
            _remember_hash(kind, file_hash, stored)
            status, message = 'queued', 'Waiting for an extraction worker'
        with get_db_connection() as conn:
            conn.execute('INSERT INTO extraction_jobs(job_id,batch_id,kind,original_filename,stored_filename,file_hash,branch,selected_date,status,message) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (job_id, batch_id, kind, original, stored, file_hash, branch, selected_date, status, message))
            conn.commit()
        if status == 'queued':
            assert _job_queue is not None
            await _job_queue.put(job_id)
        batch_jobs.append({'job_id': job_id, 'filename': original, 'status': status, 'message': message})
    return {'batch_id': batch_id, 'total': len(files), 'jobs': batch_jobs}


@router.post('/upload/tickets')
async def upload_tickets(
    files: list[UploadFile] = File(...),
    branch: str = Form(...),
    selected_date: str = Form(...),
):
    return await _batch(files, 'ticket', branch, selected_date)


@router.post('/upload/dockets')
async def upload_dockets(
    files: list[UploadFile] = File(...),
    branch: str = Form(...),
    selected_date: str = Form(...),
):
    return await _batch(files, 'docket', branch, selected_date)


@router.get('/upload/jobs/{batch_id}')
def get_upload_jobs(batch_id: str):
    with get_db_connection() as conn:
        rows = conn.execute('SELECT job_id,original_filename AS filename,status,message,provider,error,created_at,updated_at FROM extraction_jobs WHERE batch_id=? ORDER BY created_at,job_id', (batch_id,)).fetchall()
    return {'batch_id': batch_id, 'jobs': [dict(row) for row in rows]}

@router.get("/tickets/unassigned")
def get_unassigned_tickets(branch: str, selected_date: str):
    with get_db_connection() as conn:
        rows = conn.execute("SELECT filename,selected_branch,selected_date,parsed_json,issue FROM unassigned_screenshots WHERE selected_branch=? AND selected_date=? ORDER BY created_at", (branch, selected_date)).fetchall()
    return [{"filename": r["filename"], "branch": r["selected_branch"], "date": r["selected_date"], "parsed": json.loads(r["parsed_json"]), "issue": r["issue"]} for r in rows]


@router.get("/tickets")
def get_tickets(branch: str, selected_date: str):
    """Return saved ticket records for the selected branch and ticket day."""
    ticket_day = selected_date[2:4] + selected_date[5:7] + selected_date[8:10]
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ticket_records WHERE selected_branch=? AND substr(ticket_id,1,6)=? ORDER BY ticket_id",
            (branch, ticket_day),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/tickets/resolve")
def resolve_unassigned_ticket(filename: str = Form(...), branch: str = Form(...), selected_date: str = Form(...), ticket_id: str = Form(""), confirm_mismatch: bool = Form(False)):
    with get_db_connection() as conn:
        pending = conn.execute("SELECT * FROM unassigned_screenshots WHERE filename=? AND selected_branch=? AND selected_date=?", (filename, branch, selected_date)).fetchone()
    if not pending:
        raise HTTPException(404, "Unassigned screenshot not found")
    parsed = json.loads(pending["parsed_json"])
    selected_id = ticket_id.strip().lstrip("#") or str(parsed.get("ticket_id") or "").strip().lstrip("#")
    if not TICKET_ID_RE.fullmatch(selected_id):
        raise HTTPException(400, "Enter a Ticket ID matching YYMMDD-N")
    mismatches = []
    if selected_id[:6] != selected_date.replace("-", "")[2:8]:
        mismatches.append("Ticket ID day differs from selected date")
    if parsed.get("branch") and _norm(parsed["branch"]) != _norm(branch):
        mismatches.append("Ticket branch differs from selected branch")
    if mismatches and not confirm_mismatch:
        raise HTTPException(409, {"confirmation_required": True, "warnings": mismatches})
    parsed["ticket_id"] = selected_id
    with get_db_connection() as conn:
        audit = conn.execute(
            "SELECT raw_json FROM upload_audits WHERE kind='ticket:tesseract' AND filename=? ORDER BY id DESC LIMIT 1",
            (filename,),
        ).fetchone()
    mapped = _ticket_storage(parsed, filename, pending["file_hash"], branch, audit["raw_json"] if audit else "")
    record = upsert_ticket_record(mapped)
    with get_db_connection() as conn:
        conn.execute("DELETE FROM unassigned_screenshots WHERE filename=?", (filename,))
        conn.commit()
    build_verification(branch, selected_date)
    return {"ticket_id": record["ticket_id"], "status": "saved", "warnings": mismatches}
