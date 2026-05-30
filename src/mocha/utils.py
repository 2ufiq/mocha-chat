from datetime import datetime
from zoneinfo import ZoneInfo

def get_datetime_ctx(timezone: str = "Asia/Dhaka") -> str:
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("Asia/Dhaka")  # default to Dhaka timezone
    return (
        "Today's current datetime: "
        + datetime.now(tz).strftime("%A, %Y-%m-%d %I:%M:%S %p %Z")
        + f" ({tz.key})"
    )