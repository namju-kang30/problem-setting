import pymupdf as fitz
import io
from pathlib import Path
from PIL import Image
from typing import List, Dict, Any, Tuple

class PDFProcessor:
    def __init__(self, pdf_path: str):
        self.pdf_path = str(pdf_path)
        self.doc = fitz.open(self.pdf_path)
        self.page_count = len(self.doc)

    def get_page_info(self) -> List[Dict[str, Any]]:
        """Return dimensions and metadata for each page."""
        info = []
        for i, page in enumerate(self.doc):
            rect = page.rect
            info.append({
                "page_num": i + 1,
                "width": rect.width,
                "height": rect.height,
            })
        return info

    def render_page_to_image(
        self,
        page_index: int,
        zoom_ratio: float = 1.30,
        high_dpi_supersample: float = 2.0,
        max_dimension: int = 3200
    ) -> Image.Image:
        """
        Renders a PDF page to PIL Image.
        zoom_ratio: 1.30 means 130% PDF viewer zoom.
        high_dpi_supersample: 2.0 renders at double resolution for razor-sharp text and graphics.
        max_dimension: Prevents RAM exhaustion (OOM) on oversized/scanned exam papers.
        """
        if page_index < 0 or page_index >= self.page_count:
            raise ValueError(f"Page index {page_index} out of range (0-{self.page_count-1})")

        page = self.doc[page_index]
        base_w, base_h = page.rect.width, page.rect.height
        
        target_scale = zoom_ratio * high_dpi_supersample
        # Guard against gigantic bitmaps that exhaust system RAM
        if max(base_w, base_h) * target_scale > max_dimension:
            target_scale = max_dimension / max(base_w, base_h)

        mat = fitz.Matrix(target_scale, target_scale)
        
        # Render pixmap with alpha=False (white background)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        del pix  # Explicitly release native C++ pixmap memory
        return img

    def render_page_preview(self, page_index: int, max_width: int = 1200) -> Tuple[Image.Image, float]:
        """
        Renders a preview image suitable for web display and Gemini API analysis.
        Returns: (PIL.Image, scale_factor_relative_to_pdf_points)
        """
        page = self.doc[page_index]
        base_width = page.rect.width
        scale = max_width / base_width
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        del pix  # Explicitly release native C++ pixmap memory
        return img, scale

    def extract_text_blocks(self, page_index: int) -> List[Dict[str, Any]]:
        """
        Extracts all text blocks and coordinates from the page.
        """
        page = self.doc[page_index]
        blocks = page.get_text("blocks")
        result = []
        for b in blocks:
            # b = (x0, y0, x1, y1, text, block_no, block_type)
            result.append({
                "bbox": [b[0], b[1], b[2], b[3]],
                "text": b[4].strip(),
                "block_no": b[5],
                "type": b[6]
            })
        return result

    def close(self):
        if self.doc:
            self.doc.close()
