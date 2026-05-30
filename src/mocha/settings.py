import os

# LLM
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# ---- Human pacing -----------------------------------------------------------
PACING_ENABLED = os.getenv("PACING_ENABLED", "1") == "1"
READ_DELAY_MIN = float(os.getenv("READ_DELAY_MIN", "1.2"))
READ_DELAY_MAX = float(os.getenv("READ_DELAY_MAX", "2.8"))
TYPE_DELAY_PER_CHAR = float(os.getenv("TYPE_DELAY_PER_CHAR", "0.045"))
