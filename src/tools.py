# tools.py
from datetime import datetime, timedelta

def read_calendar():
    today = datetime.now().date()
    slots = [
        {"date": str(today), "time": "15:00-16:00"},
        {"date": str(today + timedelta(days=1)), "time": "10:00-11:00"},
    ]
    return {"available_slots": slots}

def get_user_prefs():
    
    return {
        "preferred_greeting": "Hi",
        "preferred_closing": "Best regards",
        "meeting_default_duration_minutes": 30,
    }
