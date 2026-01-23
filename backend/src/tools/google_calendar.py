import json
import re
import os
import sys
import asyncio
from googleapiclient.errors import HttpError
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
from typing import Optional, Dict, Any, List, Tuple
from langchain_google_genai import ChatGoogleGenerativeAI
from googleapiclient.discovery import Resource
from psycopg import AsyncConnection
from backend.src.tools.auth import get_user_service
from dotenv import load_dotenv
from backend.src.tools.google_gmail import get_sender_display_name
load_dotenv()
IST = timezone(timedelta(hours=5, minutes=30))
HOLIDAY_CALENDAR_ID = 'en.indian#holiday@group.v.calendar.google.com'

async def get_calendar_service(db, user_id: str) -> Resource:
    """Get calendar service for a user (async)."""
    return await get_user_service(db, user_id, 'calendar')

async def extract_event_details_llm(email_text: str, email_subject: str) -> Optional[Dict]:
    """Gemini extracts {summary, slots: [{date, time}], location} from email."""
    try:
        model = ChatGoogleGenerativeAI(model='gemini-2.5-flash', temperature=0.7)
        current_time = datetime.now(IST).strftime('%Y-%m-%d')
        prompt = f"""
        You are an email assistant. Extract meeting details from this email.
        
        Context:
        - Current Date (IST): {current_time}
        - Email Body: "{email_text}"
        
        Task:
        Return a valid JSON object. 
        
        CRITICAL RULES:
        1. "Next week Tuesday" = Calculate date based on {current_time}.
        2. If the email offers multiple options (e.g., "Tuesday OR Wednesday"), extract ALL of them into the 'slots' list.
        3. Default times: Morning="10:00 AM", Afternoon="02:00 PM", Evening="06:00 PM".
        4. If location is missing, default to "Online".

        JSON Structure:
        {{
            "summary": "Short Event Title",
            "slots": [
                {{ "date_str": "YYYY-MM-DD", "time_str": "HH:MM AM/PM" }},
                {{ "date_str": "YYYY-MM-DD", "time_str": "HH:MM AM/PM" }}
            ],
            "location": "Venue or 'Online'"
        }}
        
        If no event, return: {{ "error": "no_event" }}
        """
        
        response = await model.ainvoke(prompt)  
        content = response.content.strip()
        
        if content.startswith("```"):
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        
        data = json.loads(content)
        
        if "error" in data:
            return None
            
        return data
    except Exception as e:
        print(f'LLM Extraction Error: {e}')
        return None

async def check_for_holiday(service: Resource, date_obj: datetime.date) -> Tuple[bool, Optional[str]]:
    """Check Indian holidays calendar."""
    
    try:
        start_of_day = datetime.combine(date_obj, datetime.min.time()).replace(tzinfo=IST)
        end_of_day = datetime.combine(date_obj, datetime.max.time()).replace(tzinfo=IST)
        
        # Run blocking Google API call in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        events_result = await loop.run_in_executor(
            None,
            lambda: service.events().list(
                calendarId=HOLIDAY_CALENDAR_ID,
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True
            ).execute()
        )
        
        events = events_result.get('items', [])
        if events:
            return True, events[0]['summary']  # e.g., "Christmas Day"
        return False, None
    except Exception as e:
        print(f'Could not check holidays: {e}')
        return False, None  # Fail-safe: assume not holiday

async def is_slot_available(service: Resource, start_dt: datetime, end_dt: datetime) -> Tuple[bool, Optional[str]]:
    """Check personal calendar availability."""
    
    try:
        loop = asyncio.get_event_loop()
        events_result = await loop.run_in_executor(
            None,
            lambda: service.events().list(
                calendarId='primary',
                timeMin=start_dt.isoformat(),
                timeMax=end_dt.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
        )
        
        events = events_result.get('items', [])
        if not events:
            return True, None
        return False, events[0]['summary']
    except Exception as e:
        print(f'Error checking availability: {e}')
        return False, 'API Error'

async def create_calendar_event(service: Resource, details: Dict, start_dt: datetime, end_dt: datetime) -> bool:
    """Create event in primary calendar."""
    
    try:
        event_body = {
            'summary': details['summary'],
            'location': details.get('location', 'Online'),
            'description': 'Automatically added via Gemini AI.',
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Kolkata'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Kolkata'}
        }
        
        loop = asyncio.get_event_loop()
        event = await loop.run_in_executor(
            None,
            lambda: service.events().insert(calendarId='primary', body=event_body).execute()
        )
        
        print(f'Created Event: {details["summary"]}')
        return event.get('id')
    except Exception as e:
        print(f'Could not create event: {e}')
        return False

# In backend/src/tools/google_calendar.py

async def book_best_slot(db: AsyncConnection, userid: str, event_data: Dict) -> Tuple[bool, Optional[Dict], Optional[str], list]:
    """
    Checks all slots, skips holidays/conflicts, and books the first free 1hr slot.
    Returns (success, booked_details, event_id, rejection_reasons)
    """
    IST = timezone(timedelta(hours=5, minutes=30))
    rejection_reasons = []
    booked_successfully = False
    final_slot = None
    final_event_id = None # Initialize to avoid UnboundLocalError

    # 1. Initialize the actual Google Calendar Service object using the database
    from backend.src.tools.auth import get_user_service
    calendar = await get_user_service(db, userid, "calendar")

    if not calendar:
        return False, None, None, ["Authentication failed: Could not initialize Calendar service."]

    if not event_data or 'slots' not in event_data or not event_data['slots']:
        return False, None, None, ["No meeting slots provided in the extraction."]
    
    print("🔍 Finding best slot...")
    for slot in event_data['slots']:
        print(f"   Checking {slot['date_str']} {slot['time_str']} (IST)...")
        
        # Parse TZ-aware
        try:
            full_time_str = f"{slot['date_str']} {slot['time_str']} IST"
            start_dt = date_parser.parse(full_time_str, tzinfos={('IST',): IST}).astimezone(IST)
            end_dt = start_dt + timedelta(hours=1)
        except Exception as e:
            rejection_reasons.append(f"{slot['date_str']}: Invalid time format")
            continue
        
        # 1. Holiday check
        try:
            is_holiday, holiday_name = await check_for_holiday(calendar, start_dt.date())
            if is_holiday:
                print(f"   ⛔ Holiday: {holiday_name}")
                rejection_reasons.append(f"{slot['date_str']}: Holiday ({holiday_name})")
                continue
        except Exception as e:
            print(f"   ⚠️ Holiday check error: {e}")
            rejection_reasons.append(f"{slot['date_str']}: Holiday check failed")
        
        # 2. Personal conflict check
        try:
            is_free, conflict_name = await is_slot_available(calendar, start_dt, end_dt)
            if is_free:
                print(f"   ✅ FREE! Booking '{event_data['summary']}'...")
                temp_details = event_data.copy()
                temp_details['booked_slot'] = slot
                
                # Capture the actual Event ID from creation
                event_id = await create_calendar_event(calendar, temp_details, start_dt, end_dt)
                
                if event_id:
                    booked_successfully = True
                    final_slot = slot
                    final_event_id = event_id # Success!
                    print(f"   🎉 CREATED: {start_dt.strftime('%Y-%m-%d %I:%M %p IST')}")
                    break
                else:
                    rejection_reasons.append(f"{slot['date_str']}: Create failed")
            else:
                print(f"   ⛔ Busy: {conflict_name}")
                rejection_reasons.append(f"{slot['date_str']}: Conflict ({conflict_name})")
        except Exception as e:
            print(f"   ⚠️ Availability check error: {e}")
            rejection_reasons.append(f"{slot['date_str']}: API Error during check")
    
    # Returns exactly 4 values to match your main.py unpacking
    return booked_successfully, final_slot, final_event_id, rejection_reasons[:3]

async def delete_calendar_event(db: AsyncConnection, user_id: str, event_id: str):
    # Ensure 'calendar' service is retrieved correctly
    calendar = await get_user_service(db, user_id, "calendar")
    
    # ADD THIS LOG TO SEE IF IT EVEN RUNS
    print(f"🚀 ATTEMPTING DELETE: ID={event_id}")

    def _delete_sync():
        return calendar.events().delete(
            calendarId='primary', 
            eventId=event_id
        ).execute() # 🟢 MUST HAVE .execute()

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _delete_sync)
        print(f"🗑️ SUCCESS: Deleted {event_id}")
        return True
    except Exception as e:
        print(f"❌ DELETE FAILED: {e}")
        return False
    
async def generate_meeting_response_llm(
    # original_subject: str, 
    # original_body: str, 
    full_msg: dict,
    event_details: Dict, 
    booked_slot: Optional[Dict] = None,
    rejection_reasons: Optional[List[str]] = None,
    calendar_event_id: Optional[str] = None
) -> str:
    """Handles Successful Booking Confirmations and Intelligent Rejections."""
    try:
        model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.8)

        recipient_name = get_sender_display_name(full_msg)
        
        if booked_slot and calendar_event_id:
            # 🟢 SUCCESS - Event Booked!
            prompt = f"""
            You successfully booked a meeting! Send a professional CONFIRMATION.

            Start with: Dear {recipient_name},

            DETAILS:
            Use simple HTML for formatting, with <b>...</b> for bold; do not output Markdown 

            - <b>Event:<b> {event_details['summary']}
            - <b>Date:<b> {booked_slot['date_str']}
            - <b>Time:<b> {booked_slot['time_str']}
            - <b>Location:<br> {event_details.get('location', 'Online')}

            IMPORTANT: Do NOT include a "Subject:" line in your response. Write ONLY the email body.

            Start directly with the greeting.

            Sign: "Aayush's AI Assistant"
            """
        elif rejection_reasons:
            # 🔴 REJECT - Scheduling Conflicts
            prompt = f"""
            The proposed times failed. Send a polite REJECTION with alternatives.

            Start with: Dear {recipient_name},

            Use simple HTML for formatting, with <b>...</b> for bold; do not output Markdown 
            <b>REASONS:<b> {json.dumps(rejection_reasons)}
            IMPORTANT: Do NOT include a "Subject:" line in your response. Write ONLY the email body.

            Start directly with the greeting.

            Task:
            1. Explain SPECIFIC reasons (e.g., busy or holiday).
            2. Suggest alternatives: Next week Tue/Wed/Fri 2:00 PM - 4:00 PM.
            3. Sign: "Aayush's AI Assistant".
            """
        
        response = await model.ainvoke(prompt)
        return response.content.strip()
    except Exception as e:
        return "Processed your meeting request. Please check your calendar."
    
async def generate_general_llm(full_msg:dict) -> str:
    """Handles General Acknowledgements when no event is detected."""
    try:
        
        model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.7)

        recipient_name = get_sender_display_name(full_msg)
        
        prompt = f"""
        You are Aayush's AI Assistant. Acknowledge this email professionally.
        Start with: Dear {recipient_name},

        TASK:
        - If the email is a newsletter or general update (like Infosys feedback), thank them for the info.
        - ONLY mention meeting availability if the original email seems to be inquiring about your time.
        - Sign: "Aayush's AI Assistant".

        Keep it concise (1-2 sentences).
        """
        
        response = await model.ainvoke(prompt)
        return response.content.strip()
    except Exception as e:
        return "Thank you for your email. I have received it. - Aayush's AI Assistant"