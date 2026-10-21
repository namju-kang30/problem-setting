import json
import re
import io
from google import genai
from google.genai import types
from PIL import Image
from typing import List, Dict, Any, Optional
from backend.config import DEFAULT_GEMINI_MODEL, GEMINI_MODELS

PROMPT_DETECT_QUESTIONS = """
당신은 대한민국 대학수학능력시험 및 모의고사 시험지 레이아웃 분석 전문가입니다.
제시된 모의고사 시험지 페이지 이미지에서 각 **문제 영역**을 검출하여 글자, 수식, 표, 그림, 5지선다 선택지가 잘리지 않도록 **충분하고 안정적인 상하좌우 안전 여백을 포함한** 2D 바운딩 박스를 반환해주세요.

[검출 기준 및 핵심 안전 여백 규칙]
1. 모의고사는 좌/우 2단(2 Columns)으로 구성되어 있습니다. 각 단의 경계를 넘지 않도록 합니다.
2. 각 문제는 문제 번호(예: 1., 2., 11., 20. 등)로 시작하여 **5지선다 선택지(①, ②, ③, ④, ⑤) 또는 주관식 답안란**으로 끝납니다.
3. [필수 핵심 원칙: 적정 상하좌우 여백 확보 - 글자/그림/수식 잘림 방지 및 과도한 여백 배제]
   - **상단 경계(ymin)**: 문제 번호 및 첫 줄 발문, 수식 기호보다 위쪽으로 **적정 여백(약 6~9px 상당, 0.6~0.9%)**을 두어 위쪽 글자가 잘리지 않게 하세요.
   - **하단 경계(ymax)**: 5지선다 선택지(①~⑤)의 동그라미 번호 및 보기 글자 아래쪽으로 **적정 여백(약 7~10px 상당, 0.7~1.0%)**을 남기세요. (최하단 푸터 제외)
   - **좌측 경계(xmin)**: 문제 번호(예: '6.') 좌측으로 **적정 여백(약 6~9px 상당)**을 두어 문제 번호가 잘리지 않게 하세요.
   - **우측 경계(xmax)**: 본문 텍스트, 표 테두리선, 그림 등의 가장 우측 요소보다 오른쪽으로 **적정 여백(약 7~10px 상당)**을 두어 표나 수식이 잘리지 않게 하세요.
4. 절대 포함 및 검출 금지: 시험지 최하단 구분선, 저작권 문구, 페이지 번호 상자(예: 시험지 최하단 중앙의 사선 분할 페이지 번호 상자 '1/32', '32', '16' 등). 이 상자는 문제가 아니므로 절대로 문제로 검출하거나 번호를 부여하지 마세요.
5. 바운딩 박스 좌표 형식: [ymin, xmin, ymax, xmax] (0부터 1000 사이의 정수)

반드시 아래와 같은 JSON 배열 형식으로만 응답하세요:
```json
[
  {
    "question_number": 1,
    "box_2d": [ymin, xmin, ymax, xmax]
  }
]
```
"""

class GeminiExtractor:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def set_api_key(self, api_key: str):
        self.api_key = api_key
        self.client = genai.Client(api_key=self.api_key)

    def detect_questions_in_page(
        self,
        page_image: Image.Image,
        page_num: int,
        model_name: str = DEFAULT_GEMINI_MODEL
    ) -> List[Dict[str, Any]]:
        """
        Calls Gemini Vision API to detect question bounding boxes on a single page image.
        Returns list of dicts: [{"question_number": int, "box_2d": [ymin, xmin, ymax, xmax], "page_num": int}]
        """
        if not self.api_key:
            raise ValueError("Google Gemini API Key is required for AI detection.")

        candidates = [model_name, DEFAULT_GEMINI_MODEL, "gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        models_to_try = list(dict.fromkeys(filter(None, candidates)))
        last_error = None

        for model in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=[PROMPT_DETECT_QUESTIONS, page_image],
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json"
                    )
                )
                
                response_text = response.text.strip()
                data = self._parse_json_response(response_text)
                
                if isinstance(data, list) and len(data) > 0:
                    results = []
                    for item in data:
                        q_num = item.get("question_number")
                        box = item.get("box_2d")
                        if q_num is not None and box and len(box) == 4:
                            ymin, xmin, ymax, xmax = [int(coord) for coord in box]
                            # Footer boxes and footer overshoot are removed in backend.main using the page layout
                            if ymax <= ymin or xmax <= xmin:
                                continue

                            results.append({
                                "question_number": int(q_num),
                                "box_2d": [ymin, xmin, ymax, xmax],
                                "page_num": page_num,
                                "source": "gemini"
                            })
                    if results:
                        results.sort(key=lambda x: x["question_number"])
                        return results
            except Exception as e:
                last_error = e
                continue

        if last_error:
            raise RuntimeError(f"Gemini API detection failed: {str(last_error)}")
        return []

    def _parse_json_response(self, text: str) -> Any:
        """Parses JSON safely from response, stripping markdown fences if any."""
        text = text.strip()
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            text = match.group(1).strip()
        return json.loads(text)
