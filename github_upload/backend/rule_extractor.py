import pymupdf as fitz
import re
from typing import List, Dict, Any, Tuple
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

class RuleExtractor:
    """
    High-precision Heuristic & PDF-vector layout detector for Korean CSAT/Mock Exams.
    Calculates tight bounding boxes [ymin, xmin, ymax, xmax] anchored directly to
    the question header (start) and 5지선다 choices (end), eliminating footer and page-number overlap.
    """
    def __init__(self, doc: fitz.Document):
        self.doc = doc

    def detect_questions(self) -> List[Dict[str, Any]]:
        """
        Scans all pages in the PDF document and detects questions 1 ~ 20 with choice-anchored tight bounding boxes.
        Returns normalized bounding boxes [ymin, xmin, ymax, xmax] (0~1000).
        """
        all_questions = []

        for page_num in range(1, len(self.doc) + 1):
            page = self.doc[page_num - 1]
            page_w = page.rect.width
            page_h = page.rect.height

            mid_x = page_w * 0.5
            blocks = page.get_text("blocks")
            drawings = page.get_drawings()

            # Regex: starts with 1~20 followed by dot and space
            q_pattern = re.compile(r'^\s*([1-9]|1[0-9]|20)\s*\.\s*')

            detected_headers = []

            for b in blocks:
                x0, y0, x1, y1, text, block_no, block_type = b
                # Ignore top header (7%) and bottom area (y > 85%) where questions never start
                if y0 < page_h * 0.07 or y0 > page_h * 0.85 or is_footer_block(text, y0, page_h):
                    continue

                lines = text.strip().split('\n')
                if not lines:
                    continue
                first_line = lines[0].strip()

                m = q_pattern.match(first_line)
                if m:
                    q_num = int(m.group(1))
                    col = 0 if x0 < mid_x else 1
                    detected_headers.append({
                        "question_number": q_num,
                        "col": col,
                        "y_start": y0,
                        "x_start": x0,
                        "x_end": x1,
                        "block": b
                    })

            # Sort detected problems by question number
            detected_headers.sort(key=lambda item: item["question_number"])

            # Group by column
            left_qs = [q for q in detected_headers if q["col"] == 0]
            right_qs = [q for q in detected_headers if q["col"] == 1]

            # Calculate tight bounding boxes per column
            left_boxes = self._calculate_tight_boxes(
                left_qs, blocks, drawings, page_w, page_h, col_index=0, page_num=page_num
            )
            right_boxes = self._calculate_tight_boxes(
                right_qs, blocks, drawings, page_w, page_h, col_index=1, page_num=page_num
            )

            all_questions.extend(left_boxes)
            all_questions.extend(right_boxes)

        # Sort all by question number
        all_questions.sort(key=lambda x: x["question_number"])
        return all_questions

    def _calculate_tight_boxes(
        self,
        qs: List[Dict[str, Any]],
        all_blocks: List[Any],
        drawings: List[Dict[str, Any]],
        page_w: float,
        page_h: float,
        col_index: int,
        page_num: int
    ) -> List[Dict[str, Any]]:
        if not qs:
            return []

        # Sort questions by vertical start position
        qs.sort(key=lambda q: q["y_start"])
        boxes = []
        mid_x = page_w * 0.5

        # Dynamically determine the page header line boundary to prevent top black lines.
        # Only drawings ending above the first question header count; otherwise a wide
        # <보기> box, table or diagram in the top question would be mistaken for the header.
        first_q_top = qs[0]["y_start"]
        header_lines = [
            d["rect"].y1 for d in drawings
            if d["rect"].y1 < page_h * 0.25 and d["rect"].y1 <= first_q_top
            and (d["rect"].x1 - d["rect"].x0) > page_w * 0.28
        ]
        page_header_bottom = max(header_lines) if header_lines else (page_h * 0.21 if page_num == 1 else page_h * 0.125)
        content_top_limit = page_header_bottom + 4.0

        # Define column bounds with clean clearance from vertical divider at mid_x
        if col_index == 0:
            col_min_x = 10.0
            col_max_x = mid_x - 3.0
        else:
            col_min_x = mid_x + 5.0
            col_max_x = page_w - 10.0

        # Dynamically determine the page footer boundary to strictly exclude footer text and page number box
        footer_tops = [
            b[1] for b in all_blocks
            if b[1] > page_h * 0.88 and is_footer_block(b[4], b[1], page_h)
        ]
        footer_drawings = [
            d["rect"].y0 for d in drawings
            if d["rect"].y0 > page_h * 0.88 and (
                ((mid_x - page_w * 0.15) <= d["rect"].x0 <= (mid_x + page_w * 0.15)) or
                d["rect"].x0 < page_w * 0.15 or d["rect"].x1 > page_w * 0.85
            ) and (d["rect"].y1 - d["rect"].y0) < page_h * 0.05
        ]
        all_footer_tops = footer_tops + footer_drawings
        if all_footer_tops:
            content_bottom_limit = min(all_footer_tops) - 4.0
        else:
            content_bottom_limit = page_h * 0.902

        for i, q in enumerate(qs):
            q_y0 = q["y_start"]
            # The lower vertical bound is the next question in this column or content_bottom_limit
            if i + 1 < len(qs):
                q_y1_limit = qs[i+1]["y_start"] - 6.0
            else:
                q_y1_limit = content_bottom_limit

            # Collect text blocks belonging to this question
            q_blocks = []
            choice_block = None

            for b in all_blocks:
                bx0, by0, bx1, by1, btext = b[0], b[1], b[2], b[3], b[4]
                
                # Exclude top header and footers
                if by0 < page_h * 0.07 or is_footer_block(btext, by0, page_h):
                    continue

                # Must be in this column
                if col_index == 0 and bx0 >= mid_x:
                    continue
                if col_index == 1 and bx0 < mid_x:
                    continue
                
                # Check vertical zone
                if q_y0 - 6.0 <= by0 and by1 <= q_y1_limit + 15.0:
                    q_blocks.append((bx0, by0, bx1, by1, btext))
                    # Check if this block contains 5지선다 choices (①~⑤)
                    if CHOICE_PATTERN.search(btext):
                        choice_block = (bx0, by0, bx1, by1)

            # Determine true question content bottom
            if choice_block:
                true_bottom_y = choice_block[3]
            elif q_blocks:
                true_bottom_y = max(b[3] for b in q_blocks)
            else:
                true_bottom_y = q_y0 + 120.0

            # Gather all elements (text blocks + drawings) up to true_bottom_y
            q_elements = []
            for b in q_blocks:
                if b[1] <= true_bottom_y + 6.0:
                    q_elements.append((b[0], b[1], b[2], min(b[3], true_bottom_y)))

            # Collect vector drawings / boxes / diagrams strictly within this question's zone
            for d in drawings:
                rect = d.get("rect")
                if not rect:
                    continue
                rx0, ry0, rx1, ry1 = rect.x0, rect.y0, rect.x1, rect.y1
                
                # Must be in this column
                if col_index == 0 and (rx0 >= mid_x or rx1 > mid_x):
                    continue
                if col_index == 1 and (rx0 < mid_x or rx1 <= mid_x):
                    continue

                # Ignore page-wide borders or footer boxes (like page number box at bottom)
                if (rx1 - rx0) > page_w * 0.45 or (ry1 - ry0) > page_h * 0.4:
                    continue
                if ry0 > page_h * 0.88 and (ry1 - ry0) < page_h * 0.05:
                    # Exclude footer page number box and footer divider lines
                    continue
                if ry1 > true_bottom_y + 10.0:
                    # Diagram is never below the choices row!
                    continue

                # Check if inside question vertical span
                if q_y0 - 5.0 <= ry0 and ry1 <= true_bottom_y + 10.0:
                    q_elements.append((rx0, ry0, rx1, ry1))

            if q_elements:
                min_x = min(el[0] for el in q_elements)
                min_y = min(el[1] for el in q_elements)
                max_x = max(el[2] for el in q_elements)
                max_y = max(el[3] for el in q_elements)
            else:
                min_x = q["x_start"]
                min_y = q["y_start"]
                max_x = q["x_end"]
                max_y = true_bottom_y

            # Add moderate safe padding (halved)
            safe_x0 = max(col_min_x, min_x - 6.0)
            safe_x1 = min(col_max_x, max_x + 7.0)
            # The header limit may trim the top padding but never the question content itself
            safe_y0 = min(max(content_top_limit, min_y - 6.0), min_y)
            safe_y1 = min(min(q_y1_limit, max(max_y, true_bottom_y) + 5.0), content_bottom_limit)

            # Convert to 0~1000 normalized coordinates
            norm_ymin = int((safe_y0 / page_h) * 1000)
            norm_xmin = int((safe_x0 / page_w) * 1000)
            norm_ymax = int((safe_y1 / page_h) * 1000)
            norm_xmax = int((safe_x1 / page_w) * 1000)

            boxes.append({
                "question_number": q["question_number"],
                "box_2d": [norm_ymin, norm_xmin, norm_ymax, norm_xmax],
                "page_num": page_num,
                "source": "rule"
            })

        return boxes
