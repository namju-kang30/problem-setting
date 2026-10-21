import pymupdf as fitz
import os
import sys
from pathlib import Path
from PIL import Image

from backend.pdf_processor import PDFProcessor
from backend.rule_extractor import RuleExtractor
from backend.image_cropper import ImageCropper

def create_sample_mock_exam_pdf(output_pdf_path: str):
    """
    Creates a realistic 4-page mock exam PDF (20 questions total, 5 questions per page, 2 columns)
    to test the extraction and cropping pipeline.
    """
    doc = fitz.open()

    # Korean font or standard Helvetica/CID font in PyMuPDF
    # 4 pages, each 595 x 842 pt (A4)
    q_counter = 1

    for page_idx in range(4):
        page = doc.new_page(width=595, height=842)
        page_num = page_idx + 1

        # Header
        page.draw_rect(fitz.Rect(30, 25, 565, 55), color=(0.8, 0.8, 0.8), fill=(0.95, 0.95, 0.95))
        page.insert_text(fitz.Point(40, 45), f"2026학년도 대학수학능력시험 모의평가 문제지 [제 4 교시 과학탐구 영역]", fontsize=10)
        page.insert_text(fitz.Point(520, 45), f"{page_num}", fontsize=14)

        # Center dividing line
        page.draw_line(fitz.Point(297.5, 65), fitz.Point(297.5, 790), color=(0.7, 0.7, 0.7), width=0.8)

        # 5 questions per page: 3 in left col (x: 35~285), 2 in right col (x: 310~560)
        # Left column questions
        left_count = 3 if page_idx % 2 == 0 else 2
        right_count = 5 - left_count

        # Left column
        y_cursor = 80
        col_h = (780 - 80) / left_count
        for i in range(left_count):
            q_num = q_counter
            q_counter += 1
            
            top_y = y_cursor + i * col_h + 10
            # Draw question text
            page.insert_text(fitz.Point(40, top_y), f"{q_num}. 그림은 물리 실험 장치를 나타낸 것이다.", fontsize=10)
            page.insert_text(fitz.Point(40, top_y + 20), "이에 대한 설명으로 옳은 것만을 <보기>에서 고른 것은? [3점]", fontsize=8.5)
            
            # Diagram box
            page.draw_rect(fitz.Rect(50, top_y + 30, 270, top_y + 80), color=(0.4, 0.4, 0.4))
            page.insert_text(fitz.Point(110, top_y + 60), f"[Question {q_num} Diagram]", fontsize=9)

            # Choices
            page.insert_text(fitz.Point(40, top_y + 100), "(1) ㄱ   (2) ㄴ   (3) ㄱ, ㄷ   (4) ㄴ, ㄷ   (5) ㄱ, ㄴ, ㄷ", fontsize=8.5)

        # Right column
        col_h_r = (780 - 80) / right_count
        for i in range(right_count):
            q_num = q_counter
            q_counter += 1

            top_y = y_cursor + i * col_h_r + 10
            page.insert_text(fitz.Point(315, top_y), f"{q_num}. 다음은 변압기 또는 전기 회로에 대한 설명이다.", fontsize=10)
            page.insert_text(fitz.Point(315, top_y + 20), "이에 대한 설명으로 가장 적절한 것은? [3점]", fontsize=8.5)

            # Diagram box
            page.draw_rect(fitz.Rect(325, top_y + 30, 545, top_y + 90), color=(0.4, 0.4, 0.4))
            page.insert_text(fitz.Point(380, top_y + 65), f"[Question {q_num} Circuit]", fontsize=9)

            # Choices
            page.insert_text(fitz.Point(315, top_y + 115), "(1) V1/2   (2) V1   (3) 2V1   (4) 4V1   (5) 8V1", fontsize=8.5)

        # Footer
        page.insert_text(fitz.Point(280, 815), f"{page_num} / 4", fontsize=9)
        page.insert_text(fitz.Point(450, 815), "* 확인 사항을 확인하십시오.", fontsize=8)

    doc.save(output_pdf_path)
    doc.close()
    print(f"Sample mock exam PDF generated: {output_pdf_path} with 20 questions.")

def test_full_pipeline():
    # Generated into output/ (git-ignored) so running the test never touches the committed sample_exam.pdf
    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    test_pdf = output_dir / "sample_exam.pdf"
    create_sample_mock_exam_pdf(str(test_pdf))

    # 1. Process PDF
    processor = PDFProcessor(str(test_pdf))
    print(f"Page count: {processor.page_count}")
    assert processor.page_count == 4, "Should have 4 pages"

    # 2. Render Page at 130% zoom
    img_130 = processor.render_page_to_image(0, zoom_ratio=1.30, high_dpi_supersample=2.0)
    print(f"Page 1 Rendered Image (130% zoom): {img_130.size}")
    assert img_130.width > 0 and img_130.height > 0

    # 3. Detect Questions with Rule Extractor
    rule_ext = RuleExtractor(processor.doc)
    detected = rule_ext.detect_questions()
    print(f"Total questions detected: {len(detected)}")
    for q in detected:
        print(f"  Q{q['question_number']} (Page {q['page_num']}): Box = {q['box_2d']}")

    assert len(detected) == 20, f"Expected 20 questions, got {len(detected)}"

    # 4. Crop All 20 Questions
    page_images = {}
    for p_idx in range(4):
        p_num = p_idx + 1
        page_images[p_num] = processor.render_page_to_image(p_idx, zoom_ratio=1.30, high_dpi_supersample=2.0)

    cropper = ImageCropper(output_dir)
    result = cropper.process_and_save_all(
        session_id="test_session",
        page_images=page_images,
        questions=detected,
        padding=12
    )

    processor.close()

    print(f"Cropped result total questions: {result['total_questions']}")
    print(f"ZIP file generated at: {result['zip_filepath']}")
    assert result["total_questions"] == 20, "Should have cropped 20 question images"
    assert Path(result["zip_filepath"]).exists(), "ZIP file should exist"

    # 5. Every sample question spans >= 100pt (number line down to choices); a shorter crop means clipping
    min_content_pt = 100
    for item in result["questions"]:
        px_per_pt = page_images[item["page_num"]].height / 842
        min_h = int(min_content_pt * px_per_pt)
        print(f"  Q{item['question_number']}: crop height {item['height']}px (min {min_h}px)")
        assert item["height"] >= min_h, (
            f"Q{item['question_number']} crop is only {item['height']}px tall (< {min_h}px); question content was clipped"
        )

    # 6. Web API margin pass must not shrink any detected box
    from backend.main import apply_safe_question_margins
    before = {q["question_number"]: list(q["box_2d"]) for q in detected}
    for q in apply_safe_question_margins([dict(q, box_2d=list(q["box_2d"])) for q in detected]):
        b = before[q["question_number"]]
        assert q["box_2d"][0] <= b[0] and q["box_2d"][2] >= b[2], (
            f"Q{q['question_number']} box shrank in apply_safe_question_margins: {b} -> {q['box_2d']}"
        )

    print("\n[SUCCESS] Pipeline test passed with flying colors!")

if __name__ == "__main__":
    test_full_pipeline()
