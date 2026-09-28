"""Manual verification harness for vision-based extraction.

Reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment, or from a key
file whose path is the first argument (e.g. /tmp/opencode/gemini.env with a
line like GEMINI_API_KEY=...). Never writes to the database: it only parses
and maps, printing the results for manual acceptance.
"""
import json
import os
import sys


def load_key():
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    os.environ[key.strip()] = value.strip()


def main():
    load_key()
    from app.api.upload import (
        _extract_ticket_parsed,
        _extract_docket_parsed,
        _map_ticket_to_storage,
        _map_docket_to_storage,
    )

    TICKETS = [
        "data/uploads/ticket_screenshots/ticket-91f4ecda-a412-4173-b6d0-3fe343cf2cf6.jpeg",
        "data/uploads/ticket_screenshots/ticket-8fd8277e-b154-4565-b8ca-79da96c8a565.jpeg",
        "data/uploads/ticket_screenshots/ticket.png",
    ]
    DOCKETS = [
        "data/uploads/dockets/docket-c0f34c06-2033-4da9-a09e-7e96df1e13a3.jpeg",
        "data/uploads/dockets/docket-33691115-622e-424a-9179-f4c93ca60ab9.jpeg",
        "data/uploads/dockets/docket.jpeg",
    ]

    print("=== TICKETS (vision) ===")
    for p in TICKETS:
        if not os.path.exists(p):
            print(p, "-> MISSING (skipped)")
            continue
        try:
            parsed, raw, method = _extract_ticket_parsed(p)
        except Exception as error:  # noqa: BLE001
            print(p, "-> ERROR:", error)
            continue
        mapped = _map_ticket_to_storage(parsed)
        print(json.dumps({
            "image": p, "method": method,
            "ticket_number": parsed.get("ticket_number"),
            "items": parsed.get("items"),
            "restaurant": parsed.get("restaurant"),
            "date": parsed.get("date"),
            "total": parsed.get("grand_total"),
        }, ensure_ascii=False, indent=2))

    print("\n=== DOCKETS (vision) ===")
    for p in DOCKETS:
        if not os.path.exists(p):
            print(p, "-> MISSING (skipped)")
            continue
        try:
            parsed, raw, method, flags = _extract_docket_parsed(p)
        except Exception as error:  # noqa: BLE001
            print(p, "-> ERROR:", error)
            continue
        mapped = _map_docket_to_storage(
            parsed, raw, os.path.basename(p),
            extraction_method=method, vision_review_flags=flags,
        )
        print(json.dumps({
            "image": p, "method": method,
            "order": parsed.get("docket_order_no"),
            "date": parsed.get("date"),
            "time": parsed.get("time"),
            "item": parsed.get("item"),
            "type": parsed.get("discrepancy_type"),
            "handwritten_reason": parsed.get("handwritten_reason"),
            "extra": parsed.get("extra_fields"),
            "review_required": mapped["review_required"],
            "review_reason": mapped["review_reason"],
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()