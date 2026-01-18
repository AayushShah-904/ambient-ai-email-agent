import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from typing import Optional, Dict, Any
from langchain_core.tools import tool
from backend.src.tools.google_gmail import send_reply, mark_as_processed, fetch_emails
from backend.src.tools.google_calendar import extract_event_details_llm, is_slot_available, create_calendar_event, get_calendar_service,IST
from dateutil import parser as dateparser

DANGEROUS_TOOLS = {"send_gmail_reply", "create_calendar"}
SAFE_TOOLS = {"extract_meeting_from_email", "read_calendar_availability", "get_user_prefs", "process_email"}

# @tool
# def send_gmail_reply(to: str, subject: str, body: str) -> str:
#     """Send email reply using Gmail API. DANGEROUS - requires HITL approval."""
#     print(f"Email: Sent to {to}, Subject: {subject}")
#     return "Sent" if send_reply(to, subject, body) else "Failed"

# @tool  # DANGEROUS: HITL-gated
# def create_calendar(summary: str, start: str, end: str, location: str = "Online") -> str:
#     """Create calendar event. DANGEROUS - requires HITL. Use after availability check."""
#     service = get_calendar_service()
#     details = {"summary": summary, "location": location}
#     start_dt = dateparser.parse(start).replace(tzinfo=IST)
#     end_dt = dateparser.parse(end).replace(tzinfo=IST)
#     return "Created" if create_calendar_event(service, details, start_dt, end_dt) else "Failed"

@tool
async def send_gmail_reply(to: str, subject: str, body: str) -> str:
    """
    Drafts an email reply. 
    This is a DANGEROUS tool that will trigger a Human-in-the-Loop pause.
    """
    # This tool is mostly a placeholder for the LLM to 'choose' the action.
    # The actual sending happens in the hitl_checkpoint node.
    return "Drafted for approval."

@tool
async def create_calendar(summary: str, start: str, end: str, location: str = "Online") -> str:
    """
    Books a meeting on the calendar. 
    DANGEROUS tool - requires human approval.
    """
    return "Calendar event drafted for approval."

@tool  # Safe
async def process_email(msg_id: str, db=None, user_id: str = None) -> str:
    """Mark Gmail message as processed (remove UNREAD label)."""
    if not db or not user_id:
        return "Error: Database connection or user_id not provided"
    return "Processed" if await mark_as_processed(db, user_id, msg_id) else "Failed"

@tool  # Safe: read-only
async def read_calendar_availability(start: str, end: str, db=None, user_id: str = None) -> str:
    """Check calendar slot availability. Format: 'YYYY-MM-DD HH:MM' IST. Returns 'Free: True/False, Conflict: details'."""
    if not db or not user_id:
        return "Error: Database connection or user_id not provided"
    
    service = await get_calendar_service(db, user_id)
    start_dt = dateparser.parse(start).replace(tzinfo=IST)
    end_dt = dateparser.parse(end).replace(tzinfo=IST)
    is_free, conflict = await is_slot_available(service, start_dt, end_dt)
    return f"Free: {is_free}, Conflict: {conflict or 'None'}"


@tool
async def extract_meeting_from_email(subject: str, body: str) -> str:
    """Extract meeting details JSON from email text using Gemini LLM."""
    details = await extract_event_details_llm(body, subject)
    return json.dumps(details) if details else "No event found"

@tool  # Add for memory
async def get_user_prefs(thread_id: str | None=None) -> str:
    """Get user preferences from memory (signature, name prefs). TODO: SQLite."""
    return '{"signature": "Best, Aayush"}'