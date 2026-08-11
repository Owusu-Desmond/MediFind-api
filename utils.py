import json
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

GHANA_TZ = ZoneInfo("UTC")  # Ghana (GMT) is UTC+0 year-round

def parse_time_str(t_str: str) -> time:
    """Parses time string formats like '08:00', '8:00 AM', '9:00 PM', '21:00' into datetime.time."""
    t_str = t_str.strip().upper()

    # Try 12-hour format with AM/PM (e.g. 08:00 AM, 9:30 PM, 8 AM)
    for fmt in ("%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            pass

    # Try 24-hour format (e.g. 08:00, 21:30)
    for fmt in ("%H:%M", "%H"):
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            pass

    return time(8, 0)

def calculate_pharmacy_open_status(opening_hours: str | None) -> tuple[bool, str]:
    """
    Evaluates opening_hours string/JSON and returns (is_open: bool, status_text: str).
    Examples of return values:
      (True, "Open 24/7")
      (True, "Open now • Closes at 09:00 PM")
      (False, "Closed • Opens at 08:00 AM")
      (False, "Closed Today")
    """
    if not opening_hours:
        return True, "Open Today"

    raw = opening_hours.strip()
    raw_lower = raw.lower()

    # 24/7 Check
    if "24/7" in raw_lower or "24 hours" in raw_lower or "always open" in raw_lower:
        return True, "Open 24/7"

    now = datetime.now(GHANA_TZ)
    current_time = now.time()

    # 1. Structured JSON format check
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            if data.get("is_24_7"):
                return True, "Open 24/7"

            # Check if simple open_time and close_time exist in JSON
            open_str = data.get("open_time")
            close_str = data.get("close_time")
            
            # Check day-by-day schedule in JSON if provided
            day_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
            current_day_code = day_map[now.weekday()]
            schedule = data.get("schedule", {})
            
            if current_day_code in schedule:
                day_sched = schedule[current_day_code]
                if day_sched.get("closed"):
                    return False, "Closed Today"
                open_str = day_sched.get("open", open_str or "08:00")
                close_str = day_sched.get("close", close_str or "21:00")

            if open_str and close_str:
                open_t = parse_time_str(open_str)
                close_t = parse_time_str(close_str)
                
                if open_t <= close_t:
                    is_open = open_t <= current_time <= close_t
                else:
                    is_open = current_time >= open_t or current_time <= close_t

                if is_open:
                    formatted_close = datetime.combine(now.date(), close_t).strftime("%I:%M %p").lstrip("0")
                    return True, f"Open now • Closes at {formatted_close}"
                else:
                    formatted_open = datetime.combine(now.date(), open_t).strftime("%I:%M %p").lstrip("0")
                    return False, f"Closed • Opens at {formatted_open}"
        except Exception:
            pass

    # 2. Extract opening & closing times from freeform text string (e.g. "Mon - Sat: 08:00 AM - 09:00 PM")
    time_matches = re.findall(r'(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)', raw)
    if len(time_matches) >= 2:
        try:
            open_t = parse_time_str(time_matches[0])
            close_t = parse_time_str(time_matches[1])

            if open_t <= close_t:
                is_open = open_t <= current_time <= close_t
            else:
                is_open = current_time >= open_t or current_time <= close_t

            formatted_close = datetime.combine(now.date(), close_t).strftime("%I:%M %p").lstrip("0")
            formatted_open = datetime.combine(now.date(), open_t).strftime("%I:%M %p").lstrip("0")

            if is_open:
                return True, f"Open now • Closes at {formatted_close}"
            else:
                return False, f"Closed • Opens at {formatted_open}"
        except Exception:
            pass

    return True, "Open Today"
