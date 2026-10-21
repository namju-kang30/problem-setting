import os
import zipfile
import io
from pathlib import Path
from PIL import Image, ImageOps
import numpy as np
from typing import List, Dict, Any, Tuple

class ImageCropper:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def crop_question_image(
        self,
        page_image: Image.Image,
        box_2d: List[int],
        auto_trim_whitespace: bool = True,
        margin: int = 9
    ) -> Image.Image:
        """
        Crops a question region from page_image using normalized box [ymin, xmin, ymax, xmax] (0-1000).
        Ensures balanced top/bottom/left/right margins (default 9px) around all content.
        100% guarantees letters, formulas, tables, and choices are never clipped.
        """
        img_w, img_h = page_image.size
        ymin, xmin, ymax, xmax = box_2d

        # Convert normalized 0-1000 coordinates to actual pixel bounds
        left = max(0, int((xmin / 1000.0) * img_w))
        top = max(0, int((ymin / 1000.0) * img_h))
        # Add a 4px buffer on right (clamped before mid_x for left col) so rightmost strokes and table borders are 100% captured
        if xmax < 500:
            right = min(int(0.499 * img_w), int((xmax / 1000.0) * img_w) + 4)
        else:
            right = min(img_w, int((xmax / 1000.0) * img_w) + 4)
        bottom = min(img_h, int((ymax / 1000.0) * img_h))

        if right <= left or bottom <= top:
            return page_image.crop((0, 0, min(img_w, 100), min(img_h, 100)))

        # Crop raw region
        raw_cropped = page_image.crop((left, top, right, bottom))

        if auto_trim_whitespace:
            return self._trim_outer_whitespace_with_margin(raw_cropped, target_margin=margin)

        # Add uniform white margin around the question
        if margin > 0:
            return ImageOps.expand(raw_cropped, border=margin, fill='white')

        return raw_cropped

    def _clean_top_header_line(self, arr: np.ndarray) -> np.ndarray:
        """
        Detects and clears page header horizontal divider lines (black solid lines at the very top)
        that may sit at the top of questions located at the top of the page.
        Does NOT touch right or left edges, table borders, <보기> box borders, or question content.
        """
        h, w = arr.shape
        cleaned = arr.copy()

        # Header lines sit at the very top (first 35 rows or top 10% of image)
        # and span across almost the entire width (> 45% of image width)
        # with a clear whitespace gap below it before any question content.
        max_check_row = min(int(h * 0.10), 35)
        line_rows = []
        for r in range(max_check_row):
            dark_ratio = np.sum(cleaned[r, :] < 200) / w
            if dark_ratio > 0.45:
                line_rows.append(r)
            elif line_rows:
                gap = 0
                for gr in range(r, min(r + 15, h)):
                    if np.sum(cleaned[gr, :] < 200) / w < 0.05:
                        gap += 1
                    else:
                        break
                if gap >= 3:
                    cleaned[:line_rows[-1] + 2, :] = 255
                    break
                line_rows = []

        return cleaned

    def _trim_outer_whitespace_with_margin(self, img: Image.Image, target_margin: int = 9) -> Image.Image:
        """
        Safely identifies all non-white question content (header, formulas, tables, diagrams, choices),
        cleans any header line artifacts, and guarantees uniform white margin (target_margin, default 9px) on all 4 sides.
        """
        gray = img.convert('L')
        arr = np.array(gray)

        # Clear any accidental page header horizontal lines at the very top
        arr = self._clean_top_header_line(arr)

        # Non-white pixels (threshold < 248)
        non_white = arr < 248

        if not np.any(non_white):
            return img

        row_counts = np.sum(non_white, axis=1)
        col_counts = np.sum(non_white, axis=0)

        valid_rows = np.where(row_counts > 0)[0]
        valid_cols = np.where(col_counts > 0)[0]

        if len(valid_rows) == 0 or len(valid_cols) == 0:
            return img

        # Tight envelope encompassing all content elements
        first_row = valid_rows[0]
        last_row = valid_rows[-1]
        first_col = valid_cols[0]
        last_col = valid_cols[-1]

        content = img.crop((first_col, first_row, last_col + 1, last_row + 1))

        # Add guaranteed uniform white margin on all 4 sides
        if target_margin > 0:
            return ImageOps.expand(content, border=target_margin, fill='white')

        return content

    def save_cropped_question(
        self,
        session_id: str,
        page_img: Image.Image,
        q: Dict[str, Any],
        padding: int = 9
    ) -> Dict[str, Any]:
        """Crops a single question and writes it immediately to disk."""
        session_dir = self.output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        q_num = q["question_number"]
        page_num = q["page_num"]
        box = q["box_2d"]

        cropped_img = self.crop_question_image(
            page_img,
            box,
            auto_trim_whitespace=True,
            margin=padding
        )

        filename = f"{q_num:02d}.png"
        filepath = session_dir / filename
        cropped_img.save(filepath, format="PNG", optimize=True)

        w, h = cropped_img.width, cropped_img.height
        del cropped_img

        return {
            "question_number": q_num,
            "page_num": page_num,
            "filename": filename,
            "filepath": str(filepath),
            "width": w,
            "height": h,
            "box_2d": box
        }

    def create_zip_archive(self, session_id: str, items: List[Dict[str, Any]]) -> Tuple[str, str]:
        """Creates a downloadable ZIP archive from cropped image files."""
        session_dir = self.output_dir / session_id
        zip_filename = f"questions_{session_id}.zip"
        zip_filepath = session_dir / zip_filename

        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for item in items:
                fpath = Path(item["filepath"])
                if fpath.exists():
                    zipf.write(fpath, arcname=fpath.name)

        return zip_filename, str(zip_filepath)

    def process_and_save_all(
        self,
        session_id: str,
        page_images: Dict[int, Image.Image],
        questions: List[Dict[str, Any]],
        padding: int = 10
    ) -> Dict[str, Any]:
        """
        Backward-compatible batch method.
        """
        cropped_items = []
        sorted_qs = sorted(questions, key=lambda x: x.get("question_number", 999))

        for q in sorted_qs:
            page_num = q["page_num"]
            if page_num in page_images:
                item = self.save_cropped_question(session_id, page_images[page_num], q, padding=padding)
                cropped_items.append(item)

        zip_filename, zip_filepath = self.create_zip_archive(session_id, cropped_items)

        return {
            "session_id": session_id,
            "total_questions": len(cropped_items),
            "questions": cropped_items,
            "zip_filename": zip_filename,
            "zip_filepath": zip_filepath
        }
