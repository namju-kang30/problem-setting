import pymupdf as fitz
import io
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

def test_real_exam_layout_features():
    """
    Reproduces layout features of real 평가원/교육청 papers that broke detection:
    - a <보기> box and fraction choices sitting just above the footer page-number box
    - a raster figure that defines the question's right edge
    - a subject tab printed in the right page margin
    """
    from backend.main import apply_safe_question_margins
    from backend.rule_extractor import analyze_page_layout, normalized_layout

    W, H = 595, 842
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)

    page.draw_line(fitz.Point(40, 60), fitz.Point(555, 60), width=1.2)            # header rule
    page.draw_line(fitz.Point(297.5, 62), fitz.Point(297.5, 790), width=0.5)      # column divider
    page.draw_rect(fitz.Rect(565, 300, 585, 380), color=None, fill=(0.6, 0.6, 0.6))  # subject tab
    page.insert_text(fitz.Point(570, 320), "물리", fontsize=9, fontname="korea")

    # Left column: Q1 whose <보기> box and fraction choices reach down to the footer
    page.insert_text(fitz.Point(45, 80), "1. 그림은 전하의 배치를 나타낸 것이다.", fontsize=9, fontname="korea")
    page.draw_rect(fitz.Rect(45, 690, 285, 740), width=0.5)                       # <보기> box
    page.insert_text(fitz.Point(120, 690), "< 보 기 >", fontsize=8, fontname="korea")
    page.insert_text(fitz.Point(50, 765), "①", fontsize=9, fontname="korea")
    page.insert_text(fitz.Point(62, 760), "1", fontsize=7)                        # fraction numerator
    page.draw_line(fitz.Point(60, 762), fitz.Point(68, 762), width=0.4)            # fraction bar
    page.insert_text(fitz.Point(62, 770), "4", fontsize=7)                        # fraction denominator
    page.insert_text(fitz.Point(110, 765), "② 2   ③ 3   ④ 4   ⑤ 5", fontsize=9, fontname="korea")

    # Right column: Q2 with a raster figure reaching the right edge of the column
    page.insert_text(fitz.Point(305, 80), "2. 그림과 같이 회로를 구성하였다.", fontsize=9, fontname="korea")
    figure = Image.new("RGB", (200, 80), (90, 90, 90))
    buf = io.BytesIO()
    figure.save(buf, format="PNG")
    page.insert_image(fitz.Rect(400, 100, 552, 160), stream=buf.getvalue())
    page.insert_text(fitz.Point(305, 190), "① ㄱ   ② ㄴ   ③ ㄷ   ④ ㄱ, ㄴ   ⑤ ㄴ, ㄷ", fontsize=9, fontname="korea")

    # Footer: page number box and copyright notice
    page.draw_rect(fitz.Rect(280, 800, 315, 818), width=0.5)
    page.insert_text(fitz.Point(286, 812), "1", fontsize=8)
    page.insert_text(fitz.Point(302, 812), "4", fontsize=8)
    page.insert_text(fitz.Point(380, 830), "이 문제지에 관한 저작권은 한국교육과정평가원에 있습니다.", fontsize=7, fontname="korea")

    detected = {q["question_number"]: q for q in RuleExtractor(doc).detect_questions()}
    assert sorted(detected) == [1, 2], f"Expected questions [1, 2], got {sorted(detected)}"

    def to_pt(box):
        ymin, xmin, ymax, xmax = box
        return ymin * H / 1000, xmin * W / 1000, ymax * H / 1000, xmax * W / 1000

    q1_top, _, q1_bottom, _ = to_pt(detected[1]["box_2d"])
    assert q1_bottom >= 772, f"Q1 choice row (incl. fraction denominator, bottom ~772pt) was cut at {q1_bottom:.1f}pt"
    assert q1_bottom < 800, f"Q1 box ({q1_bottom:.1f}pt) runs into the footer page-number box at 800pt"
    assert q1_top > 60, f"Q1 box ({q1_top:.1f}pt) includes the header rule at 60pt"

    _, q2_left, _, q2_right = to_pt(detected[2]["box_2d"])
    assert q2_right >= 552, f"Q2 figure (right edge 552pt) was cut at {q2_right:.1f}pt"
    assert q2_right < 565, f"Q2 box ({q2_right:.1f}pt) reaches into the subject tab at 565pt"
    assert q2_left > 297.5, f"Q2 box ({q2_left:.1f}pt) crosses the column divider"

    # The web API margin pass must keep the same guarantees
    layouts = {1: normalized_layout(analyze_page_layout(page))}
    final = {q["question_number"]: q for q in apply_safe_question_margins(list(detected.values()), layouts)}
    assert 772 <= to_pt(final[1]["box_2d"])[2] < 800, f"Q1 bottom after margins: {to_pt(final[1]['box_2d'])[2]:.1f}pt"
    assert to_pt(final[2]["box_2d"])[3] < 565, f"Q2 right edge after margins: {to_pt(final[2]['box_2d'])[3]:.1f}pt"

    doc.close()
    print("[SUCCESS] Real exam layout features handled correctly!")

def test_detect_modes_with_gemini_mistakes():
    """
    Gemini output varies between runs; on real papers it sometimes stopped short of the choice row,
    labeled the footer page box as a question, or missed a question. Hybrid mode must correct all three,
    while Gemini-only mode returns Gemini's own boxes.
    """
    from unittest import mock
    from fastapi.testclient import TestClient
    from backend.main import app

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    test_pdf = output_dir / "sample_exam.pdf"
    create_sample_mock_exam_pdf(str(test_pdf))

    with fitz.open(str(test_pdf)) as doc:
        rule = {q["question_number"]: q for q in RuleExtractor(doc).detect_questions()}

    def fake_gemini(self, page_image, page_num, model_name):
        results = []
        for q in rule.values():
            if q["page_num"] != page_num or q["question_number"] == 7:  # Gemini misses question 7
                continue
            ymin, xmin, ymax, xmax = q["box_2d"]
            if q["question_number"] == 3:
                ymax = ymin + (ymax - ymin) // 2  # stops halfway, above the choice row
            results.append({"question_number": q["question_number"], "box_2d": [ymin, xmin, ymax, xmax],
                            "page_num": page_num, "source": "gemini"})
        if page_num == 1:
            # Footer page number box ("1 / 4") labeled as question 9, ahead of the real question 9
            results.insert(0, {"question_number": 9, "box_2d": [960, 460, 975, 540], "page_num": 1, "source": "gemini"})
        return results

    client = TestClient(app)
    with open(test_pdf, "rb") as f:
        session_id = client.post("/api/upload", files={"file": ("exam.pdf", f, "application/pdf")}).json()["session_id"]

    detected = {}
    with mock.patch("backend.main.GeminiExtractor.detect_questions_in_page", fake_gemini):
        for mode in ["hybrid", "gemini"]:
            res = client.post("/api/detect", json={"session_id": session_id, "api_key": "test", "detection_mode": mode})
            assert res.status_code == 200, res.text
            detected[mode] = {q["question_number"]: q for q in res.json()["questions"]}

    hybrid = detected["hybrid"]
    assert sorted(hybrid) == list(range(1, 21)), f"Hybrid should detect 1~20, got {sorted(hybrid)}"
    assert hybrid[9]["page_num"] == rule[9]["page_num"], "Footer box labeled 9 replaced the real question 9"
    assert hybrid[3]["box_2d"][2] >= rule[3]["box_2d"][2], "Hybrid kept Gemini's box that stops above the choices"
    assert hybrid[7]["source"] == "rule", "Question 7 missed by Gemini should be filled in from the rule result"

    gemini_only = detected["gemini"]
    assert 7 not in gemini_only, "Gemini-only mode must not mix in rule-based results"
    assert gemini_only[3]["box_2d"][2] < rule[3]["box_2d"][2], "Gemini-only mode must not apply rule correction"

    print("[SUCCESS] Gemini/hybrid detection modes behave as labeled!")

if __name__ == "__main__":
    test_full_pipeline()
    test_real_exam_layout_features()
    test_detect_modes_with_gemini_mistakes()
