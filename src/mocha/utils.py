from datetime import datetime
from zoneinfo import ZoneInfo

def get_datetime_ctx(timezone: str = "Asia/Dhaka") -> str:
    try:
        tz = ZoneInfo(timezone)
    except Exception as e:
        tz = ZoneInfo("Asia/Dhaka")  # default to Dhaka timezone
    return datetime.now(tz).strftime("%A, %Y-%m-%d %H:%M:%S %Z") + f"({tz.key})"
