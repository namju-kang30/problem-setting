@echo off
title ExamCrop AI - 모의고사 20문제 자동 분할 추출기

python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않거나 환경 변수에 등록되지 않았습니다.
    echo Python 3.10 이상을 설치해주세요.
    echo.
    pause
    exit /b
)

python main.py
if errorlevel 1 (
    echo.
    pause
)
