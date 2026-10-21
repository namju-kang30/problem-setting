import os
import uuid
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any

import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import BASE_DIR, UPLOAD_DIR, OUTPUT_DIR, STATIC_DIR, DEFAULT_ZOOM_RATIO, DEFAULT_GEMINI_MODEL, GEMINI_MODELS
from backend.pdf_processor import PDFProcessor
from backend.gemini_extractor import GeminiExtractor
from backend.rule_extractor import RuleExtractor
from backend.image_cropper import ImageCropper

app = FastAPI(title="모의고사 20문제 130% 자동 분할 추출기", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cropper = ImageCropper(OUTPUT_DIR)

def apply_safe_question_margins(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Guarantees generous, balanced top/bottom/left/right margins for every question bounding box,
    preventing any text, formulas, diagrams, tables, or choices from being clipped.
    Maintains clean separation between adjacent questions and respects page margins/footers.
    """
    if not questions:
        return questions

    pages: Dict[int, List[Dict[str, Any]]] = {}
    for q in questions:
        p = q.get("page_num", 1)
        pages.setdefault(p, []).append(q)

    result = []

    for p_num, page_qs in pages.items():
        left_col = []
        right_col = []
        for q in page_qs:
            box = q.get("box_2d", [0, 0, 0, 0])
            mid_x = (box[1] + box[3]) / 2.0
            if mid_x < 500:
                left_col.append(q)
            else:
                right_col.append(q)

        for col, (col_min, col_max) in [(left_col, (10, 497)), (right_col, (504, 990))]:
            col.sort(key=lambda item: item["box_2d"][0])
            for i, q in enumerate(col):
                ymin, xmin, ymax, xmax = q["box_2d"]

                # Page header boundary limit to prevent top black divider lines on top questions
                header_top_limit = 210 if p_num == 1 else 127
                prev_bottom = col[i - 1]["box_2d"][2] if i > 0 else header_top_limit
                next_top = col[i + 1]["box_2d"][0] if i + 1 < len(col) else 936

                # Expand top: give at least 6 units margin, staying clear of prev question and page header line
                safe_ymin = max(prev_bottom + 2, ymin - 6)
                # Header limit may trim the added margin but never cut into the detected box
                safe_ymin = min(max(header_top_limit, safe_ymin), ymin)

                # Expand bottom: give at least 5 units margin below choices, staying clear of next question.
                # For the bottom question in each column, ymax already encompasses choices; give modest +2 margin.
                bottom_pad = 2 if i + 1 == len(col) else 5
                safe_ymax = min(next_top - 2, ymax + bottom_pad)
                safe_ymax = max(safe_ymax, ymax)

                # Expand left: give at least 6 units margin, respecting column left limit
                safe_xmin = max(col_min, xmin - 6)
                safe_xmin = min(safe_xmin, xmin)

                # Expand right: give at least 7 units margin, respecting column right limit
                safe_xmax = min(col_max, xmax + 7)
                safe_xmax = max(safe_xmax, xmax)

                q["box_2d"] = [int(safe_ymin), int(safe_xmin), int(safe_ymax), int(safe_xmax)]
                result.append(q)

    result.sort(key=lambda x: x.get("question_number", 0))
    return result

# Pydantic models for API
class QuestionBox(BaseModel):
    question_number: int
    page_num: int
    box_2d: List[int] # [ymin, xmin, ymax, xmax] (0~1000)

class DetectRequest(BaseModel):
    session_id: str
    api_key: Optional[str] = None
    model_name: Optional[str] = DEFAULT_GEMINI_MODEL
    detection_mode: Optional[str] = "hybrid"  # "gemini", "rule", "hybrid"

class CropRequest(BaseModel):
    session_id: str
    questions: List[QuestionBox]
    zoom_ratio: Optional[float] = 1.30  # 130% zoom
    padding: Optional[int] = 9

class VerifyKeyRequest(BaseModel):
    api_key: str

@app.post("/api/verify-gemini-key")
async def verify_gemini_key(req: VerifyKeyRequest):
    """Verifies if the provided Gemini API key is valid."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=req.api_key)
        
        # Test candidate models in priority order
        test_models = [DEFAULT_GEMINI_MODEL, "gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        test_models = list(dict.fromkeys(filter(None, test_models)))
        last_error = None
        working_model = None

        for m_name in test_models:
            try:
                model = genai.GenerativeModel(m_name)
                resp = model.generate_content("Hello! Respond with 'OK'.")
                working_model = m_name
                break
            except Exception as e:
                last_error = e
                err_str = str(e)
                # If it's authentication failure (invalid key), stop immediately
                if "API_KEY_INVALID" in err_str or "PERMISSION_DENIED" in err_str or "invalid api key" in err_str.lower():
                    raise e
                # If model is deprecated/not found (404), continue to next candidate
                continue

        if working_model:
            return {"success": True, "message": f"API 키 인증에 성공하였습니다. (사용 모델: {working_model})", "model": working_model}
        else:
            raise last_error if last_error else Exception("사용 가능한 Gemini 모델을 찾을 수 없습니다.")
    except Exception as e:
        return {"success": False, "message": f"API 키 인증 실패: {str(e)}"}

@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """
    Receives PDF, saves it, renders page previews, and returns metadata.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다.")

    session_id = uuid.uuid4().hex[:12]
    session_upload_dir = UPLOAD_DIR / session_id
    session_upload_dir.mkdir(parents=True, exist_ok=True)
    
    pdf_path = session_upload_dir / "exam.pdf"
    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        processor = PDFProcessor(str(pdf_path))
        page_count = processor.page_count
        pages_info = []

        # Render preview images for each page
        preview_dir = session_upload_dir / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)

        for page_idx in range(page_count):
            page_num = page_idx + 1
            preview_img, scale = processor.render_page_preview(page_idx, max_width=1200)
            preview_file = preview_dir / f"page_{page_num}.png"
            preview_img.save(preview_file, format="PNG")

            pages_info.append({
                "page_num": page_num,
                "preview_url": f"/api/preview/{session_id}/{page_num}",
                "width": preview_img.width,
                "height": preview_img.height,
            })

        processor.close()

        return {
            "session_id": session_id,
            "filename": file.filename,
            "page_count": page_count,
            "pages": pages_info
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 처리 중 오류 발생: {str(e)}")

@app.get("/api/preview/{session_id}/{page_num}")
async def get_page_preview(session_id: str, page_num: int):
    preview_file = UPLOAD_DIR / session_id / "previews" / f"page_{page_num}.png"
    if not preview_file.exists():
        raise HTTPException(status_code=404, detail="미리보기 이미지를 찾을 수 없습니다.")
    return FileResponse(preview_file, media_type="image/png")

@app.post("/api/detect")
async def detect_questions(req: DetectRequest):
    """
    Detects question boxes using Gemini AI and/or Rule layout parser.
    """
    session_id = req.session_id
    pdf_path = UPLOAD_DIR / session_id / "exam.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="업로드된 PDF 세션을 찾을 수 없습니다.")

    processor = PDFProcessor(str(pdf_path))
    all_detected = []
    detection_log = []

    use_gemini = (req.detection_mode in ["gemini", "hybrid"]) and bool(req.api_key)

    if use_gemini:
        try:
            gemini_ext = GeminiExtractor(api_key=req.api_key)
            preview_dir = UPLOAD_DIR / session_id / "previews"
            
            for page_idx in range(processor.page_count):
                page_num = page_idx + 1
                from PIL import Image
                page_img = Image.open(preview_dir / f"page_{page_num}.png")
                
                try:
                    page_results = gemini_ext.detect_questions_in_page(
                        page_img,
                        page_num=page_num,
                        model_name=req.model_name or DEFAULT_GEMINI_MODEL
                    )
                    all_detected.extend(page_results)
                    detection_log.append(f"{page_num}페이지: Gemini AI가 {len(page_results)}개 문제 감지 완료")
                except Exception as e:
                    detection_log.append(f"{page_num}페이지 Gemini 감지 실패 ({str(e)}), 룰베이스 분석으로 전환")
                    # Fallback for this page
                    rule_ext = RuleExtractor(processor.doc)
                    rule_results = [q for q in rule_ext.detect_questions() if q["page_num"] == page_num]
                    all_detected.extend(rule_results)
        except Exception as e:
            detection_log.append(f"Gemini API 전체 오류: {str(e)}. 전체 룰베이스 분석 적용.")
            rule_ext = RuleExtractor(processor.doc)
            all_detected = rule_ext.detect_questions()
    else:
        detection_log.append("자체 레이아웃 룰베이스 분석기를 사용하여 문제 영역을 감지합니다.")
        rule_ext = RuleExtractor(processor.doc)
        all_detected = rule_ext.detect_questions()

    processor.close()

    # Deduplicate and sort by question number
    seen_qnums = {}
    unique_detected = []
    for q in all_detected:
        qn = q.get("question_number")
        if qn and qn not in seen_qnums:
            seen_qnums[qn] = True
            unique_detected.append(q)

    # Hybrid Refinement: If Gemini was used, cross-reference with RuleExtractor to guarantee
    # that boxes stop right below choices and never overlap footer page numbers / copyright notices
    if use_gemini:
        try:
            processor_refine = PDFProcessor(str(pdf_path))
            rule_refine = RuleExtractor(processor_refine.doc)
            rule_boxes = {r["question_number"]: r for r in rule_refine.detect_questions()}
            processor_refine.close()

            for q in unique_detected:
                qn = q.get("question_number")
                if qn in rule_boxes:
                    r_box = rule_boxes[qn]["box_2d"]
                    # If Gemini ymax is significantly lower than choice-anchored rule ymax (footer overshoot)
                    if q["box_2d"][2] > r_box[2] + 25:
                        q["box_2d"][2] = r_box[2]
                    # If Gemini xmax is significantly wider than rule xmax
                    if q["box_2d"][3] > r_box[3] + 30:
                        q["box_2d"][3] = r_box[3]
        except Exception:
            pass

    # Filter out false detections (such as footer page number box '1/32' or '32')
    valid_detected = []
    for q in unique_detected:
        qn = q.get("question_number", 0)
        box = q.get("box_2d", [0, 0, 0, 0])
        ymin, xmin, ymax, xmax = box
        h_box = ymax - ymin

        # The footer page number box is located in footer region (ymin >= 870) with small height (< 60)
        is_page_box = (
            ymin >= 870 and h_box < 60 and (
                (350 <= xmin <= 550 and 450 <= xmax <= 650) or
                (qn in [16, 32, 20, 1, 2] and ymin >= 880 and h_box < 55) or
                qn > 30
            )
        )
        if is_page_box:
            continue
        valid_detected.append(q)
    unique_detected = valid_detected

    # Apply safe margins to all detected question boxes
    unique_detected = apply_safe_question_margins(unique_detected)
    unique_detected.sort(key=lambda x: x.get("question_number", 0))

    return {
        "session_id": session_id,
        "detection_mode": req.detection_mode,
        "logs": detection_log,
        "total_detected": len(unique_detected),
        "questions": unique_detected
    }

@app.post("/api/crop")
async def crop_questions(req: CropRequest):
    """
    Renders pages at 130% zoom (or requested ratio) and crops detected questions safely.
    Uses page-by-page streaming to keep RAM usage minimal (prevents OOM / Windows freezing).
    """
    import gc
    session_id = req.session_id
    pdf_path = UPLOAD_DIR / session_id / "exam.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="업로드된 PDF 세션을 찾을 수 없습니다.")

    zoom_ratio = req.zoom_ratio or DEFAULT_ZOOM_RATIO
    padding = req.padding if req.padding is not None else 9

    processor = PDFProcessor(str(pdf_path))
    q_dicts = [q.model_dump() for q in req.questions]
    
    # Group questions by page
    questions_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for q in q_dicts:
        p_num = q["page_num"]
        if p_num not in questions_by_page:
            questions_by_page[p_num] = []
        questions_by_page[p_num].append(q)

    cropped_items = []

    # Process page-by-page: render 1 page, crop its questions, then immediately free bitmap memory
    for p_num in sorted(questions_by_page.keys()):
        page_idx = p_num - 1
        if 0 <= page_idx < processor.page_count:
            page_img = processor.render_page_to_image(page_idx, zoom_ratio=zoom_ratio, high_dpi_supersample=2.0)
            
            for q in questions_by_page[p_num]:
                item = cropper.save_cropped_question(
                    session_id=session_id,
                    page_img=page_img,
                    q=q,
                    padding=padding
                )
                cropped_items.append(item)

            del page_img
            gc.collect()

    processor.close()

    # Sort results by question number
    cropped_items.sort(key=lambda x: x.get("question_number", 0))

    # Create ZIP archive
    zip_filename, zip_filepath = cropper.create_zip_archive(session_id, cropped_items)

    # Attach URLs
    for q in cropped_items:
        q["image_url"] = f"/api/image/{session_id}/{q['filename']}"

    return {
        "session_id": session_id,
        "total_questions": len(cropped_items),
        "questions": cropped_items,
        "zip_filename": zip_filename,
        "zip_filepath": zip_filepath,
        "zip_url": f"/api/download-zip/{session_id}",
        "zoom_ratio": zoom_ratio
    }

@app.get("/api/image/{session_id}/{filename}")
async def get_cropped_image(session_id: str, filename: str):
    image_file = OUTPUT_DIR / session_id / filename
    if not image_file.exists():
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
    return FileResponse(image_file, media_type="image/png")

@app.get("/api/download-zip/{session_id}")
async def download_zip(session_id: str):
    zip_file = OUTPUT_DIR / session_id / f"questions_{session_id}.zip"
    if not zip_file.exists():
        raise HTTPException(status_code=404, detail="압축 파일을 찾을 수 없습니다.")
    return FileResponse(
        zip_file,
        media_type="application/zip",
        filename=f"모의고사_20문제_130프로_추출_{session_id}.zip"
    )

# Mount static files for the web interface
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
