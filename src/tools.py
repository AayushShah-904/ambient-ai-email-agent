from typing import Dict, Any

# Accept **kwargs so the tool never crashes on extra input
def read_calendar(**kwargs) -> Dict[str, Any]:
    # We ignore kwargs for now, but this prevents the crash
    return {
        "free_slots": [
            {"day": "Monday", "start": "15:00", "end": "16:00"},
            {"day": "Wednesday", "start": "10:00", "end": "10:30"},
        ]
    }

def get_user_prefs(**kwargs) -> Dict[str, str]:
    return {
        "greeting": "Hi",
        "signoff": "Best regards,\nAayush",
    }