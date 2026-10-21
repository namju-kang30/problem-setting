import os
import sys
import subprocess

# 1. 필수 패키지 자동 검사 및 설치
REQUIRED_MODULES = [
    ("fastapi", "fastapi>=0.110.0"),
    ("uvicorn", "uvicorn[standard]>=0.29.0"),
    ("fitz", "pymupdf>=1.24.0"),
    ("google.genai", "google-genai>=1.0.0"),
    ("multipart", "python-multipart>=0.0.9"),
    ("PIL", "pillow>=10.0.0"),
    ("numpy", "numpy>=1.24.0"),
    ("pydantic", "pydantic>=2.0.0"),
]

missing_pkgs = []
for mod_name, pkg_spec in REQUIRED_MODULES:
    try:
        __import__(mod_name)
    except ImportError:
        missing_pkgs.append(pkg_spec)

if missing_pkgs:
    print("=" * 65)
    print("  [ExamCrop AI] 초기 실행 준비 중...")
    print("  필수 라이브러리가 설치되어 있지 않아 자동으로 설치합니다.")
    print("  잠시만 기다려주세요 (인터넷 환경에 따라 1~2분 소요될 수 있습니다)...")
    print("=" * 65)
    req_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
        print("\n  [성공] 필수 라이브러리 설치가 완료되었습니다!\n")
    except Exception as e:
        print(f"\n  [오류] 라이브러리 설치 중 오류가 발생했습니다: {e}")
        input("엔터 키를 누르면 종료됩니다...")
        sys.exit(1)

import socket
import webbrowser
import threading
import time
import uvicorn


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def find_available_port(start_port: int = 8000) -> int:
    port = start_port
    while port < start_port + 20:
        if not is_port_in_use(port):
            return port
        port += 1
    return start_port

def open_browser(port: int):
    time.sleep(1.5)
    url = f"http://127.0.0.1:{port}"
    try:
        webbrowser.open_new_tab(url)
    except Exception:
        pass

if __name__ == "__main__":
    port = find_available_port(8000)
    url = f"http://127.0.0.1:{port}"
    
    print("=" * 65)
    print("  [ExamCrop AI] 모의고사 20문제 130% 고화질 자동 분할 추출기")
    print("=" * 65)
    print(f"  웹 브라우저가 자동으로 실행됩니다: {url}")
    print("  만약 자동으로 열리지 않으면 위 주소를 복사하여 인터넷 창에 입력하세요.")
    print("=" * 65)
    
    # Launch browser in background thread
    t = threading.Thread(target=open_browser, args=(port,), daemon=True)
    t.start()
    
    # Start FastAPI server
    uvicorn.run("backend.main:app", host="127.0.0.1", port=port, reload=False, log_level="info")


