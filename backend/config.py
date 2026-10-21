import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Default Scale: 130% zoom in standard PDF viewer
# In PDF standard, 100% = 72 DPI.
# At 130%, scale factor = 1.3. For razor-sharp rendering, we can supersample at scale 2.6 (200% of 130%) or render at matrix scale 1.3 * DPI multiplier.
DEFAULT_ZOOM_RATIO = 1.30  # 130%

# Default Gemini model
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
# Fallback order when a model is unavailable (gemini-2.0 / 1.5 models have been retired)
GEMINI_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest"
]
