import math
import pymupdf as fitz
import re
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image

# Regular expression patterns for choices (5지선다)
CHOICE_PATTERN = re.compile(r'①|②|③|④|⑤|\([1-5]\)|[①-⑤]')

# Patterns that indicate page footers / notices / page numbers
FOOTER_PATTERN = re.compile(
    r'확인\s*사항|답안지|성명\s*과|수험\s*번호|저작권|한국교육과정평가원|EBS|'
    r'이\s*문제지에\s*관한\s*저작권|전재.*금지|'
    r'^\s*\d+\s*(?:/|\s+)\s*\d+\s*$|'  # e.g. "3 32", "1 / 4"
    r'^\s*\d+\s*$'                     # single number like "32"
)

def is_footer_block(text: str, y0: float, page_h: float) -> bool:
    """
    Detects whether a text block is a page footer or copyright notice.
    Guarantees that question text, <보기> boxes, and choices ①~⑤ are NEVER classified as footer.
    """
    t = text.strip()
    if not t:
        return False
    
    # Question content is never footer
    if re.search(r'[①-⑤]|\([1-5]\)|<보\s*기>|\[[1-4]점\]|[ㄱ-ㄷ]\.', t):
        return False

    # Footer elements reside strictly in the bottom 12% of the page (y > 88%)
    if y0 < page_h * 0.88:
        return False

    if FOOTER_PATTERN.search(t):
        return True

    if "저작권" in t or "평가원" in t or "확인" in t or "문제지" in t or "답안" in t or "EBS" in t:
        return True

    return False

# Question header: block whose first line starts with 1~20 followed by a dot (e.g. "7.", "12 .")
QUESTION_HEADER_PATTERN = re.compile(r'^\s*([1-9]|1[0-9]|20)\s*\.\s*')

# Header rule typed as box-drawing characters instead of drawn as a vector line (e.g. "━━━━")
TEXT_RULE_PATTERN = re.compile(r'^[━─═_\s]+$')


def _find_question_headers(blocks: List[Any], page_w: float, page_h: float, mid_x: float) -> List[Dict[str, Any]]:
    headers = []
    for b in blocks:
        x0, y0, x1, y1, text = b[:5]
        # Ignore top header (7%) and bottom area (y > 85%) where questions never start
        if y0 < page_h * 0.07 or y0 > page_h * 0.85 or is_footer_block(text, y0, page_h):
            continue
        m = QUESTION_HEADER_PATTERN.match(text.strip().split('\n')[0].strip())
        if m:
            headers.append({
                "question_number": int(m.group(1)),
                "col": 0 if x0 < mid_x else 1,
                "y_start": y0,
                "x_start": x0,
                "x_end": x1,
            })
    return headers


def _overlaps(a: fitz.Rect, b: fitz.Rect, pad: float = 0.0) -> bool:
    # Works for zero-width/height line rects too, unlike Rect.intersects
    return a.x0 <= b.x1 + pad and a.x1 >= b.x0 - pad and a.y0 <= b.y1 + pad and a.y1 >= b.y0 - pad


def analyze_page_layout(page: fitz.Page) -> Dict[str, Any]:
    """
    Reads the page's own structure instead of assuming fixed positions (all values in PDF points):
    - mid_x: the vertical column divider line (falls back to the page center)
    - header_bottom: lowest full-width header rule above the first question, drawn as a vector line
      or typed as '━━━' text (None if the page has none)
    - footer_top: top of the page-number box and copyright notice
    - columns: (left, right) x-range of each column. The outer edges follow the header rule, so a
      subject tab printed in the page margin (e.g. '물리학Ⅱ') is never inside a column.
    """
    page_w, page_h = page.rect.width, page.rect.height
    blocks = page.get_text("blocks")
    drawings = page.get_drawings()

    dividers = [
        d["rect"] for d in drawings
        if d["rect"].width < 3 and d["rect"].height > page_h * 0.4
        and abs((d["rect"].x0 + d["rect"].x1) / 2 - page_w / 2) < page_w * 0.1
    ]
    mid_x = (dividers[0].x0 + dividers[0].x1) / 2 if dividers else page_w * 0.5

    headers = _find_question_headers(blocks, page_w, page_h, mid_x)
    first_q_top = min((h["y_start"] for h in headers), default=page_h * 0.25)

    rules = [d["rect"] for d in drawings if d["rect"].height < 3 and d["rect"].width > page_w * 0.7]
    rules += [
        fitz.Rect(b[:4]) for b in blocks
        if b[4].strip() and TEXT_RULE_PATTERN.match(b[4]) and (b[2] - b[0]) > page_w * 0.7
    ]
    rules = [r for r in rules if r.y1 <= first_q_top and r.y1 < page_h * 0.3]
    header_bottom = max((r.y1 for r in rules), default=None)

    if rules:
        widest = max(rules, key=lambda r: r.width)
        content_left, content_right = widest.x0, widest.x1
    else:
        # No header rule: assume the page is laid out symmetrically around its left question margin
        left_starts = [h["x_start"] for h in headers if h["col"] == 0]
        content_left = max(0.0, min(left_starts) - 8.0) if left_starts else page_w * 0.05
        content_right = page_w - content_left

    # Footer: page number ("9/32") and copyright notice, plus the frame drawn around the page number.
    # A block on the same line as a choice row is never footer: a fraction numerator can look like a lone number.
    choice_rows = [(b[1], b[3]) for b in blocks if CHOICE_PATTERN.search(b[4])]
    footer_rects = [
        fitz.Rect(b[:4]) for b in blocks
        if is_footer_block(b[4], b[1], page_h)
        and not any(b[1] < cy1 and b[3] > cy0 for cy0, cy1 in choice_rows)
    ]
    footer_rects += [
        d["rect"] for d in drawings
        if d["rect"].y0 > page_h * 0.85 and any(_overlaps(d["rect"], fr, pad=6.0) for fr in footer_rects)
    ]
    footer_top = min((r.y0 for r in footer_rects), default=page_h * 0.92)
    # Whatever was detected, the footer never starts above the lowest choice row
    footer_top = max(footer_top, max((cy1 for _, cy1 in choice_rows), default=0.0) + 2.0)

    return {
        "page_w": page_w,
        "page_h": page_h,
        "mid_x": mid_x,
        "header_bottom": header_bottom,
        "footer_top": footer_top,
        "columns": [(content_left - 4.0, mid_x - 4.0), (mid_x + 5.0, content_right + 4.0)],
        "question_headers": headers,
        "blocks": blocks,
        "drawings": drawings,
    }


def normalized_layout(layout: Dict[str, Any]) -> Dict[str, Any]:
    """Converts a page layout to the 0~1000 coordinates used by question boxes."""
    w, h = layout["page_w"], layout["page_h"]
    header = layout["header_bottom"]
    return {
        "mid_x": layout["mid_x"] / w * 1000,
        "header_bottom": math.ceil(header / h * 1000) if header is not None else None,
        "footer_top": math.floor(layout["footer_top"] / h * 1000),
        "columns": [(math.ceil(x0 / w * 1000), math.floor(x1 / w * 1000)) for x0, x1 in layout["columns"]],
    }


class RuleExtractor:
    """
    Layout-aware question detector for Korean CSAT/Mock Exams.
    Each question box spans its full column width (the cropper trims surrounding whitespace afterwards)
    and runs vertically from the question number down to its 5지선다 choice row, staying clear of the
    page header rule, the footer page-number box and the subject tab in the margin.
    """
    def __init__(self, doc: fitz.Document):
        self.doc = doc

    def detect_questions(self) -> List[Dict[str, Any]]:
        """
        Scans all pages in the PDF document and detects questions 1 ~ 20.
        Returns normalized bounding boxes [ymin, xmin, ymax, xmax] (0~1000).
        """
        all_questions = []

        for page_num in range(1, len(self.doc) + 1):
            page = self.doc[page_num - 1]
            layout = analyze_page_layout(page)
            images = [fitz.Rect(im["bbox"]) for im in page.get_image_info()]

            for col_index in (0, 1):
                qs = [q for q in layout["question_headers"] if q["col"] == col_index]
                all_questions.extend(self._calculate_boxes(layout, qs, images, col_index, page_num))

        all_questions.sort(key=lambda x: x["question_number"])
        return all_questions

    def _calculate_boxes(
        self,
        layout: Dict[str, Any],
        qs: List[Dict[str, Any]],
        images: List[fitz.Rect],
        col_index: int,
        page_num: int
    ) -> List[Dict[str, Any]]:
        if not qs:
            return []

        page_w, page_h = layout["page_w"], layout["page_h"]
        col_min_x, col_max_x = layout["columns"][col_index]
        header_bottom = layout["header_bottom"]
        content_top_limit = header_bottom + 2.0 if header_bottom is not None else page_h * 0.05
        content_bottom_limit = layout["footer_top"] - 2.0

        # Everything printed in this column: text, vector drawings and raster images (figures are often images).
        # An element belongs to the column when its horizontal center lies inside it, which leaves out the
        # divider line, page-wide header rules and the subject tab in the margin.
        elements: List[Tuple[fitz.Rect, bool]] = []
        for b in layout["blocks"]:
            if not is_footer_block(b[4], b[1], page_h):
                elements.append((fitz.Rect(b[:4]), bool(CHOICE_PATTERN.search(b[4]))))
        elements += [(d["rect"], False) for d in layout["drawings"]]
        elements += [(r, False) for r in images]
        elements = [(r, c) for r, c in elements if col_min_x <= (r.x0 + r.x1) / 2 <= col_max_x]

        qs = sorted(qs, key=lambda q: q["y_start"])
        boxes = []

        for i, q in enumerate(qs):
            q_top = q["y_start"]
            # A question ends before the next question in this column, or at the footer
            zone_bottom = qs[i + 1]["y_start"] - 2.0 if i + 1 < len(qs) else content_bottom_limit
            members = [(r, c) for r, c in elements if r.y0 >= q_top - 6.0 and r.y1 <= zone_bottom + 2.0]

            choices = [r for r, c in members if c]
            if choices:
                last_row = max(choices, key=lambda r: r.y1)
                # Fraction choices put numerators/denominators in separate blocks on the same row
                bottom = max(r.y1 for r, _ in members if r.y0 < last_row.y1 and r.y1 > last_row.y0)
            elif members:
                bottom = max(r.y1 for r, _ in members)
            else:
                bottom = q_top + 120.0

            top = min([q_top] + [r.y0 for r, _ in members])
            # The header limit may trim the top padding but never the question content itself
            safe_y0 = min(max(content_top_limit, top - 6.0), top)
            safe_y1 = max(min(bottom + 5.0, zone_bottom, content_bottom_limit), bottom)

            # Round outward so the 0~1000 box never cuts into content
            boxes.append({
                "question_number": q["question_number"],
                "box_2d": [
                    math.floor(safe_y0 / page_h * 1000),
                    math.floor(col_min_x / page_w * 1000),
                    math.ceil(safe_y1 / page_h * 1000),
                    math.ceil(col_max_x / page_w * 1000),
                ],
                "page_num": page_num,
                "source": "rule"
            })

        return boxes
