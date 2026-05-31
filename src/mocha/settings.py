import os

# LLM
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# ---- Human pacing -----------------------------------------------------------
PACING_ENABLED = os.getenv("PACING_ENABLED", "1") == "1"
READ_DELAY_MIN = float(os.getenv("READ_DELAY_MIN", "1.2"))
READ_DELAY_MAX = float(os.getenv("READ_DELAY_MAX", "2.8"))
TYPE_DELAY_PER_CHAR = float(os.getenv("TYPE_DELAY_PER_CHAR", "0.045"))

# ---- Memory / compaction ----------------------------------------------------
# How many recent `history` entries the LLM sees verbatim each turn.
# Smaller = cheaper prompts but less recent context for the model.
KEEP_RECENT = int(os.getenv("KEEP_RECENT", "16"))

# How many entries to fold into `memory` per /api/compact call.
# Invariant: COMPACT_INTERVAL <= KEEP_RECENT — otherwise unfolded entries
# can fall out of the live window before being summarized, creating a
# context gap for the LLM. See chat.html maybeCompact() for the full model.
COMPACT_INTERVAL = int(os.getenv("COMPACT_INTERVAL", "10"))
