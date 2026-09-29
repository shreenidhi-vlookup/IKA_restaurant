"""Local OCR extraction for text-based POS ticket screenshots."""
import json
import os
import re
import shutil
from collections import defaultdict
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

from app.extraction.gemini import TicketExtraction


def _tesseract_module():
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("Ticket OCR requires pytesseract. Install it with: python -m pip install pytesseract") from exc

    command = os.getenv("TESSERACT_CMD", "").strip()
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
    elif not shutil.which("tesseract"):
        windows_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.isfile(windows_path):
            pytesseract.pytesseract.tesseract_cmd = windows_path
        else:
            raise RuntimeError(
                "Ticket OCR requires the Tesseract 5 engine. Install Tesseract OCR and add it to PATH, "
                "or set TESSERACT_CMD in .env to the full tesseract.exe path."
            )
    return pytesseract


def _ocr_words(image: Image.Image, pytesseract, page_segmentation: int = 6) -> list[dict[str, Any]]:
    data = pytesseract.image_to_data(image, lang="eng", config=f"--oem 1 --psm {page_segmentation}", output_type=pytesseract.Output.DICT)
    words = []
    for index, text in enumerate(data["text"]):
        text = str(text).strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (ValueError, TypeError):
            confidence = -1
        if confidence < 0:
            continue
        x, y, width, height = (int(data[key][index]) for key in ("left", "top", "width", "height"))
        words.append({"text": text, "conf": confidence, "x": x, "y": y, "w": width, "h": height})
    return words


def _line_groups(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["y"] + item["h"] / 2, item["x"])):
        center = word["y"] + word["h"] / 2
        if groups:
            previous_center = sum(item["y"] + item["h"] / 2 for item in groups[-1]) / len(groups[-1])
            tolerance = max(12, min(34, word["h"] * 1.05))
            if abs(center - previous_center) <= tolerance:
                groups[-1].append(word)
                continue
        groups.append([word])
    for group in groups:
        group.sort(key=lambda item: item["x"])
    return groups


def _group_text(group: list[dict[str, Any]]) -> str:
    return " ".join(word["text"] for word in group)


def _normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _field_value(groups: list[list[dict[str, Any]]], label: str, image_width: int) -> str | None:
    wanted = _normalized(label)
    for group_index, group in enumerate(groups):
        text = _group_text(group)
        compact = _normalized(text)
        if wanted not in compact:
            continue
        label_words = [word for word in group if wanted in _normalized(word["text"])]
        if not label_words:
            label_words = group
        label_center = sum(word["x"] + word["w"] / 2 for word in label_words) / len(label_words)
        label_right = max(word["x"] + word["w"] for word in label_words)
        same_line = [
            word for word in group
            if word["x"] >= label_right - 2 and word not in label_words
            and abs((word["x"] + word["w"] / 2) - label_center) < image_width * 0.19
        ]
        if same_line:
            value = " ".join(word["text"] for word in same_line).strip(" :-")
            if value:
                return value
        label_bottom = max(word["y"] + word["h"] for word in group)
        candidates = []
        for next_group in groups[group_index + 1:]:
            top = min(word["y"] for word in next_group)
            if top < label_bottom or top - label_bottom > 160:
                continue
            near_label = [word for word in next_group if abs((word["x"] + word["w"] / 2) - label_center) < image_width * 0.19]
            if near_label:
                candidates.append((top - label_bottom, near_label))
        if candidates:
            _, value_words = min(candidates, key=lambda item: item[0])
            return " ".join(word["text"] for word in sorted(value_words, key=lambda item: item["x"])).strip(" :-") or None
    return None


def _column_boundaries(header: list[dict[str, Any]], width: int) -> list[float]:
    labels = {"item": None, "category": None, "price": None, "qty": None, "total": None}
    for word in header:
        name = _normalized(word["text"])
        if name in labels and labels[name] is None:
            labels[name] = word["x"]
    fallback = [0.05 * width, 0.37 * width, 0.55 * width, 0.72 * width, 0.88 * width]
    starts = [labels[key] if labels[key] is not None else fallback[index] for index, key in enumerate(labels)]
    return [max(0, starts[index + 1] - width * (0.05 if index == len(starts) - 2 else 0.015)) for index in range(len(starts) - 1)]


def _column_index(x: float, boundaries: list[float]) -> int:
    for index, boundary in enumerate(boundaries):
        if x < boundary:
            return index
    return len(boundaries)


def _clean_amount(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\d[\d,]*(?:\.\d{1,2})?", value.replace("O", "0"))
    return match.group(0).replace(",", "") if match else None


def _clean_money(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"(?<=\d)[-](?=\d{2}(?:\D|$))", ".", value)
    normalized = re.sub(r"(?<!\d)[fF](?=\d{2}(?:\D|$))", "7", normalized.replace("O", "0"))
    amount = _clean_amount(normalized)
    if not amount:
        return None
    if "." in amount:
        return amount
    digits = re.sub(r"\D", "", amount)
    if len(digits) >= 3:
        return f"{digits[:-2]}.{digits[-2:]}"
    return amount


def _clean_category(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    aliases = {"foops": "FOODS", "brinks": "DRINKS"}
    if cleaned.casefold() in aliases:
        return aliases[cleaned.casefold()]
    return cleaned


def _fallback_ticket_fields(text: str) -> dict[str, str | None]:
    """Recover common ticket fields from OCR text when spatial label alignment fails."""
    result: dict[str, str | None] = {}
    date_match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-](?:19|20)?\d{2})\b", text)
    if date_match:
        result["date"] = date_match.group(1)
    terminal_match = re.search(r"\b(?:Till?|Terminal)\s*[-:#]?\s*\d+\b", text, re.I)
    if terminal_match:
        terminal = re.sub(r"\s+", "", terminal_match.group(0))
        result["terminal"] = re.sub(r"^Terminal", "Till", terminal, flags=re.I)
    table_match = re.search(r"\bTable\s*[:#-]?\s*(\d{1,4}[A-Za-z]?)\b", text, re.I)
    if table_match:
        result["table"] = table_match.group(1)
    department_context = re.search(r"\bDepartment\b([\s\S]{0,60})", text, re.I)
    department_match = re.search(r"\b(TAKE\s*AWAY|RESTAURANT|DELIVERY|COLLECTION|BAR)\b", department_context.group(1), re.I) if department_context else None
    if department_match:
        result["department"] = re.sub(r"\s+", " ", department_match.group(1)).upper()
    payment_context = re.search(r"Payment\s*Status([\s\S]{0,45})", text, re.I)
    payment_match = re.search(r"\b(PAID|UNPAID|PENDING|REFUNDED)\b", payment_context.group(1), re.I) if payment_context else None
    if payment_match:
        result["payment_status"] = payment_match.group(1).title()
    user_match = re.search(
        r"\bUser\b\s*(?:Payment\s*Status)?\s*[:#-]?\s*([A-Z][A-Z' -]{1,28}?)(?=\s+(?:Paid|Unpaid|Pending|Refunded)\b|\s+Credit\s*Card\b|$)",
        text, re.I | re.S,
    )
    if user_match:
        user = re.sub(r"\s+", " ", user_match.group(1)).strip(" :-")
        if user and not re.search(r"\b(?:Date|Terminal|Table|Department|Payment|Status|Items)\b", user, re.I):
            result["user"] = user
    credit_match = re.search(r"Credit\s*Card\b[^\d\n]{0,18}([\d,]+[.,]\d{2})", text, re.I)
    if credit_match:
        result["credit_card"] = credit_match.group(1).replace(",", ".")
    return result


def _parse_score(parsed: dict[str, Any]) -> int:
    scalar_fields = ("ticket_id", "branch", "date", "terminal", "table", "department", "user", "payment_status", "credit_card", "ticket_total", "grand_total", "charged")
    return sum(bool(parsed.get(key)) for key in scalar_fields) + len(parsed.get("items") or []) * 3


def _strikethrough_line(gray: Image.Image, boxes: list[tuple[int, int, int, int]]) -> bool:
    pixels = gray.load()
    for left, top, right, bottom in boxes:
        width = right - left
        height = bottom - top
        if width < 18 or height < 5:
            continue
        start_y = top + int(height * 0.28)
        end_y = top + int(height * 0.72)
        for y in range(max(0, start_y), min(gray.height, end_y + 1)):
            run = 0
            longest = 0
            for x in range(max(0, left), min(gray.width, right)):
                if pixels[x, y] < 195:
                    run += 1
                    longest = max(longest, run)
                else:
                    run = 0
            if longest >= max(16, int(width * 0.36)):
                return True
    return False


def _repair_horizontal_strokes(image: Image.Image, words: list[dict[str, Any]]) -> Image.Image:
    """Erase long horizontal strokes only in the detected item table before a second OCR pass."""
    groups = _line_groups(words)
    lines = [_normalized(_group_text(group)) for group in groups]
    header_index = next((i for i, line in enumerate(lines) if all(label in line for label in ("item", "price", "qty", "total"))), None)
    if header_index is not None:
        start_y = max(word["y"] + word["h"] for word in groups[header_index])
        search_from = header_index + 1
    else:
        # Ticket detail screenshots sent through messaging apps can omit the
        # table headings. Infer the body start from the repeated POS column grid.
        boundaries = _column_boundaries([], image.width)
        body_index = None
        for index, group in enumerate(groups):
            columns: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for word in group:
                columns[_column_index(word["x"], boundaries)].append(word)
            price = _clean_money(" ".join(word["text"] for word in columns[2]))
            quantity = " ".join(word["text"] for word in columns[3])
            total = _clean_money(" ".join(word["text"] for word in columns[4]))
            if price and re.search(r"\d", quantity) and total:
                body_index = index
                break
        if body_index is None:
            return image
        start_y = max(0, min(word["y"] for word in groups[body_index]) - 8)
        search_from = body_index + 1
    footer_index = next((i for i in range(search_from, len(groups)) if "tickettotal" in lines[i]), None)
    end_y = min((word["y"] for word in groups[footer_index]), default=image.height) if footer_index is not None else image.height
    if end_y <= start_y:
        return image

    result = image.copy()
    gray = ImageOps.grayscale(image)
    gray_pixels = gray.load()
    pixels = result.load()
    min_run = max(28, int(image.width * 0.12))
    x_start, x_end = int(image.width * 0.025), int(image.width * 0.975)
    for y in range(max(2, start_y), min(image.height - 2, end_y)):
        run_start = None
        for x in range(x_start, x_end + 1):
            dark = x < x_end and gray_pixels[x, y] < 210
            if dark and run_start is None:
                run_start = x
            elif not dark and run_start is not None:
                run_end = x
                if run_end - run_start >= min_run and run_end - run_start <= image.width * 0.88:
                    for repair_x in range(run_start, run_end):
                        above = pixels[repair_x, y - 2]
                        below = pixels[repair_x, y + 2]
                        pixels[repair_x, y] = tuple((a + b) // 2 for a, b in zip(above, below))
                run_start = None
    return result


def _row_background_color(image: Image.Image, top: int, bottom: int) -> tuple[int, int, int] | None:
    """Estimate a row's background from bright pixels across the table, excluding glyphs."""
    top = max(0, min(top, image.height - 1))
    bottom = max(top + 1, min(bottom, image.height))
    crop = image.crop((int(image.width * 0.03), top, int(image.width * 0.97), bottom)).convert("RGB")
    pixels = list(crop.getdata())
    stride = max(1, len(pixels) // 4000)
    sample = [pixel for pixel in pixels[::stride] if min(pixel) >= 180]
    if not sample:
        return None
    channels = [sorted(pixel[channel] for pixel in sample) for channel in range(3)]
    return tuple(values[len(values) // 2] for values in channels)


def _row_tint(image: Image.Image, top: int, bottom: int, reference_top: int, reference_bottom: int) -> bool:
    """Detect light red/pink tint relative to the row immediately above this one."""
    current = _row_background_color(image, top, bottom)
    reference = _row_background_color(image, reference_top, reference_bottom)
    if current is None or reference is None or min(current) < 215:
        return False
    red_excess = current[0] - min(current[1], current[2])
    reference_excess = reference[0] - min(reference[1], reference[2])
    green_drop = reference[1] - current[1]
    blue_drop = reference[2] - current[2]
    return red_excess >= 7 and red_excess - reference_excess >= 4 and max(green_drop, blue_drop) >= 3


def _tinted_bands(image: Image.Image, top: int, bottom: int) -> list[tuple[int, int]]:
    """Find full-width light-red item bands, then validate each against the row above."""
    pixels = image.convert("RGB").load()
    x_values = range(int(image.width * 0.035), int(image.width * 0.965), max(1, image.width // 80))
    tinted_rows = []
    for y in range(max(0, top), min(image.height, bottom)):
        samples = [pixels[x, y] for x in x_values if min(pixels[x, y]) >= 180]
        if not samples:
            continue
        channels = [sorted(pixel[channel] for pixel in samples) for channel in range(3)]
        color = tuple(values[len(values) // 2] for values in channels)
        tinted_rows.append((y, color[0] - min(color[1], color[2]) >= 7 and min(color) >= 215))
    runs = []
    start = previous = None
    for y, tinted in tinted_rows:
        if tinted:
            if start is None:
                start = y
            previous = y
        elif start is not None:
            if previous - start >= max(8, image.height * 0.006):
                runs.append((start, previous + 1))
            start = previous = None
    if start is not None and previous - start >= max(8, image.height * 0.006):
        runs.append((start, previous + 1))
    result = []
    for start, end in runs:
        height = end - start
        reference_bottom = max(top, start - 2)
        reference_top = max(top, reference_bottom - height)
        if reference_bottom > reference_top and _row_tint(image, start, end, reference_top, reference_bottom):
            result.append((start, end))
    return result


def _tesseract_cell(image: Image.Image, bounds: tuple[int, int, int, int], pytesseract, threshold: bool = True) -> str:
    crop = image.crop(bounds).convert("L")
    if threshold:
        crop = crop.point(lambda value: 0 if value < 180 else 255)
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS)
    return pytesseract.image_to_string(crop, lang="eng", config="--oem 1 --psm 7").strip()


def _tesseract_row_name(image: Image.Image, bounds: tuple[int, int, int, int], pytesseract) -> str:
    """Use a multiline OCR pass for faded names inside tinted/struck item rows."""
    crop = ImageOps.autocontrast(image.crop(bounds).convert("L"))
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS)
    return re.sub(r"\s+", " ", pytesseract.image_to_string(crop, lang="eng", config="--oem 1 --psm 6")).strip()


def _parse_ticket(image: Image.Image, words: list[dict[str, Any]], gray: Image.Image, pytesseract=None) -> dict[str, Any]:
    groups = _line_groups(words)
    full_text = "\n".join(_group_text(group) for group in groups)
    ticket_id_match = re.search(r"#?\s*(\d{6}-\d+)\b", full_text)
    branch = next((line.strip() for line in full_text.splitlines() if re.search(r"haweli", line, re.I)), None)
    branch = re.sub(r"\s+", " ", branch) if branch else None

    lower_lines = [_normalized(_group_text(group)) for group in groups]
    table_header_index = next((index for index, line in enumerate(lower_lines) if all(label in line for label in ("item", "price", "qty", "total"))), None)
    if table_header_index is None:
        # WhatsApp ticket-detail screenshots often crop off the column headings.
        # The item rows retain consistent POS column positions, so locate the
        # first row by its price/quantity/total cells and use geometric defaults.
        fallback_boundaries = _column_boundaries([], image.width)
        first_item_index = None
        for index, group in enumerate(groups):
            columns: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for word in group:
                columns[_column_index(word["x"], fallback_boundaries)].append(word)
            price_text = " ".join(word["text"] for word in columns[2])
            quantity_text = " ".join(word["text"] for word in columns[3])
            total_text = " ".join(word["text"] for word in columns[4])
            if _clean_money(price_text) and re.search(r"\d", quantity_text) and _clean_money(total_text):
                first_item_index = index
                break
        if first_item_index is not None:
            table_header_index = first_item_index - 1
    items: list[dict[str, Any]] = []
    if table_header_index is not None:
        header = groups[table_header_index] if table_header_index >= 0 else []
        boundaries = _column_boundaries(header, image.width)
        candidates: list[dict[str, Any]] = []
        pending_names: list[str] = []
        for group in groups[max(0, table_header_index + 1):]:
            line = _group_text(group)
            if re.search(r"ticket\s+total", line, re.I):
                break
            columns: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for word in group:
                columns[_column_index(word["x"], boundaries)].append(word)
            price_text = " ".join(word["text"] for word in columns[2])
            quantity_text = " ".join(word["text"] for word in columns[3])
            total_text = " ".join(word["text"] for word in columns[4])
            amount_columns_present = bool(_clean_money(price_text) and _clean_money(total_text) and re.search(r"\d", quantity_text))
            name_words = columns[0]
            if amount_columns_present and name_words:
                row_name = " ".join(word["text"] for word in name_words).strip()
                modifier = None
                category_words = columns[1]
                if row_name.startswith("("):
                    modifier_parts = [row_name]
                    if category_words:
                        modifier_parts.extend(word["text"] for word in category_words[:-1])
                        category_words = category_words[-1:]
                    modifier = " ".join(modifier_parts)
                    row_name = " ".join(pending_names).strip()
                    pending_names = []
                elif pending_names:
                    row_name = " ".join(pending_names + [row_name]).strip()
                    pending_names = []
                boxes = [(word["x"], word["y"], word["x"] + word["w"], word["y"] + word["h"]) for word in name_words]
                candidates.append({
                    "name": row_name,
                    "category": _clean_category(" ".join(word["text"] for word in category_words)),
                    "price": _clean_money(price_text),
                    "qty": _clean_amount(quantity_text),
                    "total": _clean_money(total_text),
                    "is_void": False,
                    "signals": {"row_tint": False, "strikethrough_line": False, "void_label_text": False},
                    "modifiers": [modifier] if modifier else [],
                    "_quantity_text": quantity_text,
                    "_name_boxes": boxes,
                    "_top": min(word["y"] for word in group),
                    "_bottom": max(word["y"] + word["h"] for word in group),
                    "_name_words": name_words,
                })
            elif name_words and candidates:
                extra = " ".join(word["text"] for word in name_words).strip()
                if extra:
                    if extra.startswith(("(", "*")) or re.search(r"\d[.,]\d{2}\)?$", _group_text(group)):
                        candidates[-1]["modifiers"].append(_group_text(group))
                    elif re.search(r"\b\d+\s*pcs\b|\b(large|small)\b", extra, re.I):
                        candidates[-1]["name"] += " " + extra
                    else:
                        # A plain text line immediately below a measured item row
                        # is usually its wrapped name (e.g. "CHICKEN SEEKH" /
                        # "KEBAB"), not the next item's prefix.
                        candidates[-1]["name"] = f"{candidates[-1]['name']} {extra}".strip()
                    candidates[-1]["_name_boxes"].extend((word["x"], word["y"], word["x"] + word["w"], word["y"] + word["h"]) for word in name_words)
                    candidates[-1]["_bottom"] = max(candidates[-1]["_bottom"], max(word["y"] + word["h"] for word in name_words))
            elif name_words:
                extra = " ".join(word["text"] for word in name_words).strip()
                if extra and not extra.startswith(("(", "*")):
                    pending_names.append(extra)
        if pytesseract is not None:
            table_top = max((word["y"] + word["h"] for word in header), default=0)
            footer_index = next((i for i in range(table_header_index + 1, len(groups)) if "tickettotal" in lower_lines[i]), None)
            table_bottom = min((word["y"] for word in groups[footer_index]), default=image.height) if footer_index is not None else image.height
            bands = _tinted_bands(image, table_top, table_bottom)
            item_left = round(image.width * 0.035)
            category_left, price_left, quantity_left, total_left = (round(value) for value in boundaries)
            for band_top, band_bottom in bands:
                overlapping = [candidate for candidate in candidates if candidate["_top"] < band_bottom and candidate["_bottom"] > band_top]
                if overlapping:
                    name_box = (item_left + 2, band_top, category_left - 3, band_bottom)
                    recovered_name = _tesseract_row_name(image, name_box, pytesseract)
                    void_label = bool(re.search(r"\(\s*(?:void|veid)\s*\)", recovered_name, re.I))
                    recovered_name = re.sub(r"\s*\(\s*(?:void|veid)\s*\)\s*", " ", recovered_name, flags=re.I).strip()
                    recovered_name = re.sub(r"\s+", " ", recovered_name)
                    current = overlapping[0]
                    if recovered_name and len(_normalized(recovered_name)) > len(_normalized(current["name"])):
                        current["name"] = recovered_name + (" (Void)" if void_label else "")
                    if void_label:
                        current["signals"]["void_label_text"] = True
                    continue
                pad = max(2, round((band_bottom - band_top) * 0.04))
                row_top, row_bottom = max(table_top, band_top - pad), min(table_bottom, band_bottom + pad)
                name = _tesseract_row_name(image, (item_left, row_top, category_left + 1, row_bottom), pytesseract)
                category = _tesseract_cell(image, (category_left - 9, row_top, price_left + 2, row_bottom), pytesseract)
                price_text = _tesseract_cell(image, (price_left - 8, row_top, quantity_left - 25, row_bottom), pytesseract, threshold=False)
                quantity_text = _tesseract_cell(image, (quantity_left + 5, row_top, total_left + 10, row_bottom), pytesseract, threshold=False)
                total_text = _tesseract_cell(image, (total_left + 15, row_top, round(image.width * 0.97), row_bottom), pytesseract, threshold=False)
                price, total = _clean_money(price_text), _clean_money(total_text)
                if not name or not price:
                    continue
                name_box = (item_left + 2, band_top, category_left - 3, band_bottom)
                struck = _strikethrough_line(gray, [name_box])
                label = bool(re.search(r"\(\s*(?:void|veid|[^\w\s]eid)\s*\)", name, re.I))
                name = re.sub(r"\s*\(\s*(?:void|veid|[^\w\s]eid)\s*\)\s*", " ", name, flags=re.I).strip()
                qty = _clean_amount(quantity_text)
                if price == total:
                    qty = "1"
                candidates.append({
                    "name": re.sub(r"\s+", " ", name), "category": _clean_category(category),
                    "price": price, "qty": qty, "total": total, "modifier": None,
                    "modifiers": [], "is_void": True,
                    "signals": {"row_tint": True, "strikethrough_line": struck, "void_label_text": label},
                    "void_confidence": "high" if struck or label else None, "review_flags": [],
                    "_name_boxes": [name_box], "_top": band_top, "_bottom": band_bottom,
                    "_name_words": [], "_quantity_text": quantity_text,
                })
            candidates.sort(key=lambda candidate: candidate["_top"])
        for index, item in enumerate(candidates):
            label = bool(re.search(r"\(\s*void\s*\)\s*$", item["name"], re.I))
            struck = _strikethrough_line(gray, item["_name_boxes"])
            previous_bottom = candidates[index - 1]["_bottom"] if index else item["_top"] - 2
            next_top = candidates[index + 1]["_top"] if index + 1 < len(candidates) else item["_bottom"] + 30
            row_top = max(item["_top"] - 4, (previous_bottom + item["_top"]) // 2)
            row_bottom = min(item["_bottom"] + 5, (item["_bottom"] + next_top) // 2)
            if index:
                reference_top = candidates[index - 1]["_top"]
                reference_bottom = candidates[index - 1]["_bottom"]
            else:
                reference_height = max(1, row_bottom - row_top)
                reference_top = max(0, row_top - reference_height)
                reference_bottom = max(reference_top + 1, row_top - 1)
            tinted = _row_tint(image, row_top, row_bottom, reference_top, reference_bottom)
            item["modifier"] = " ".join(item["modifiers"]) or None
            item["signals"] = {
                "row_tint": tinted,
                "strikethrough_line": struck,
                "void_label_text": label,
            }
            item["is_void"] = tinted or struck
            if item.get("is_void") and "+" in item.get("_quantity_text", "") and item.get("price") == item.get("total"):
                item["qty"] = "1"
            item["void_confidence"] = "low" if struck and not tinted else ("high" if tinted and (struck or label) else None)
            item["review_flags"] = ["strikethrough without row tint; spot-check void status"] if struck and not tinted else []
            items.append(item)
        for item in candidates:
            for key in ("_name_boxes", "_top", "_bottom", "_name_words", "_quantity_text"):
                item.pop(key, None)

    def money_after(label: str) -> str | None:
        for group in groups:
            text = _group_text(group)
            match = re.search(rf"{label}\s*:?\s*\D*([\d,]+\.\d{{2}})", text, re.I)
            if match:
                return match.group(1).replace(",", "")
        return None

    parsed = {
        "ticket_id": ticket_id_match.group(1) if ticket_id_match else None,
        "branch": branch,
        "date": _field_value(groups, "Date", image.width),
        "terminal": _field_value(groups, "Terminal", image.width),
        "table": _field_value(groups, "Table", image.width),
        "department": _field_value(groups, "Department", image.width),
        "user": _field_value(groups, "User", image.width),
        "payment_status": _field_value(groups, "Payment Status", image.width),
        "credit_card": _field_value(groups, "Credit Card", image.width),
        "items": items,
        "ticket_total": money_after("Ticket Total"),
        "grand_total": money_after("Grand Total"),
        "charged": money_after("Charged"),
        "extra_fields": [],
    }
    fallback_fields = _fallback_ticket_fields(full_text)
    for field, value in fallback_fields.items():
        if not parsed.get(field):
            parsed[field] = value
    if not parsed.get("date") and ticket_id_match:
        ticket_day = ticket_id_match.group(1)[:6]
        parsed["date"] = f"{int(ticket_day[4:6])}/{int(ticket_day[2:4])}/20{ticket_day[:2]}"
    # Keep every recognized OCR line available for audit/review, including fields
    # the current ticket layout parser does not yet map.
    return TicketExtraction.model_validate(parsed).model_dump(mode="json")


def extract_ticket(path: str) -> tuple[dict[str, Any], str]:
    pytesseract = _tesseract_module()
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    if image.width < 600:
        image = image.resize((int(image.width * 1.5), int(image.height * 1.5)), Image.Resampling.LANCZOS)
    image = ImageEnhance.Contrast(image).enhance(1.12)
    original_gray = ImageOps.grayscale(image)
    passes = []
    for psm in (6, 4, 11):
        words = _ocr_words(image, pytesseract, psm)
        parsed_pass = _parse_ticket(image, words, original_gray, pytesseract)
        text_pass = "\n".join(_group_text(group) for group in _line_groups(words))
        passes.append({"psm": psm, "words": words, "parsed": parsed_pass, "text": text_pass})
    # Select the richest layout, preferring PSM 6 on ties, then fill missing
    # scalar fields from alternate passes rather than letting one layout win all.
    passes.sort(key=lambda item: (_parse_score(item["parsed"]), item["psm"] == 6), reverse=True)
    best = passes[0]
    original_words = best["words"]
    original_parsed = best["parsed"]
    for alternate in passes[1:]:
        for key, value in alternate["parsed"].items():
            if key != "items" and not original_parsed.get(key) and value:
                original_parsed[key] = value
        if len(alternate["parsed"].get("items") or []) > len(original_parsed.get("items") or []):
            original_parsed["items"] = alternate["parsed"]["items"]

    cleaned_image = _repair_horizontal_strokes(image, original_words)
    cleaned_words = _ocr_words(cleaned_image, pytesseract, best["psm"]) if cleaned_image is not image else original_words
    cleaned_text = "\n".join(_group_text(group) for group in _line_groups(cleaned_words))
    parsed = original_parsed
    # The repaired pass can recover a crossed-out label, but its pixel edits may
    # damage neighboring item names and amounts. Use it only as corroboration.
    cleaned_void_labels = [
        re.sub(r"\s+", " ", match.group(1)).strip() + " (Void)"
        for line in cleaned_text.splitlines()
        if (match := re.search(r"^(.+?)\s*\(\s*void\s*\)", line, re.I))
    ]
    void_items = [item for item in parsed["items"] if item["is_void"]]
    for item, cleaned_name in zip(void_items, cleaned_void_labels):
        item["name"] = cleaned_name
        item["signals"]["void_label_text"] = True
        item["void_confidence"] = "high" if item["signals"]["row_tint"] else "low"
    raw = json.dumps({
        "engine": "tesseract",
        "original_text": best["text"],
        "alternate_texts": [{"psm": item["psm"], "text": item["text"]} for item in passes[1:]],
        "line_cleaned_text": cleaned_text,
        "extraction": parsed,
    }, ensure_ascii=False)
    return parsed, raw
