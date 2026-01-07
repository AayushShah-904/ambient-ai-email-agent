import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import timedelta,timezone
import time
from dateutil import parser as dateparser
from src.tools.tools import DANGEROUS_TOOLS
from src.graph import create_graph
from src.hitl_handler import handle_hitl
from src.tools.calendar import (
    get_calendar_service, extract_event_details_llm, 
    check_for_holiday, is_slot_available, create_calendar_event
)

print("=== CALENDAR EVENT + HITL TEST ===")

# 1. Test Extraction
print("\n1. 🤖 Extract Meeting")
sample_email = {
    "subject": "Meeting Options: Next Mon 2PM, Wed 3PM, or Fri morning?",
    "body": """Hi Aayush,
Hoping to schedule our Q1 sync. Available these slots?
1. Next Monday 2PM (1hr)
2. Next Wednesday 3PM (45min)  
3. This Friday 10AM (30min)
Please confirm which works + add to calendar. Thanks!
Sarah"""
}

details_raw = extract_event_details_llm(sample_email["body"], sample_email["subject"])
print(f"📥 Extracted: {json.dumps(details_raw, indent=2)}")

details = details_raw if isinstance(details_raw, dict) else json.loads(details_raw)
slot = details['slots'][0]  # First slot

# 2. Calendar Service
print("\n2. 🔑 Calendar Service")
calendar = get_calendar_service()
print("✅ Service ready")

# 3. Pre-checks improvements
print("\n3. 📅 Pre-flight Checks")
# Define IST explicitly to stop the UnknownTimezoneWarning
tz_ist = timezone(timedelta(hours=5, minutes=30))
tzinfos = {"IST": tz_ist}

start_str = f"{slot['date_str']} 10:00 AM IST"
end_str = f"{slot['date_str']} 11:00 AM IST"

# Pass tzinfos to the parser
start_dt = dateparser.parse(start_str, tzinfos=tzinfos).astimezone(tz_ist)
end_dt = dateparser.parse(end_str, tzinfos=tzinfos).astimezone(tz_ist)

holiday, hname = check_for_holiday(calendar, start_dt.date())
avail, conflict = is_slot_available(calendar, start_dt, end_dt)

print(f"Slot: {start_str} → {end_str}")
print(f"Free: {avail} | Holiday: {holiday} ({hname})")

# 4. FULL LANGGRAPH + HITL TEST
print("\n4. 🚀 LangGraph HITL Flow")
app = create_graph()
config = {"configurable": {"thread_id": f"hitl_calendar_test_{int(time.time())}"}}
state = {"mail": sample_email, "messages": []}

print("Running agent...")
# The logical way to run the external loop
result = app.invoke(state, config)

while True:
    current_state = app.get_state(config)
    
    # Check if we are stuck at the human-approval gate
    if current_state.next == ("hitl_checkpoint",):
        pending_tool = current_state.values.get("tool_name")
        pending_args = current_state.values.get("tool_args")
        
        print(f"\n✋ STOP: Agent drafted {pending_tool}")
        decision = input("Approve/Deny/Edit? [a/d/e]: ").lower()

        edit_values = {}
        if decision in ["e", "edit"]:
            new_start = input(f"Enter new start time [{pending_args.get('start')}]: ")
            if new_start: edit_values["start"] = new_start
        
        # Use hitl_handler to modify the state
        handle_hitl(app, config, decision, edit_values={}) 
        
        # Resume the graph
        result = app.invoke(None, config) 
    elif current_state.next:
        # If it's a safe tool, just let it run
        result = app.invoke(None, config)
    else:
        # Reached END
        break
print(f"Final result: {result.get('final_reply', 'Complete')}")

# 5. Manual test unchanged
# ...
print("\n🎉 CALENDAR + HITL FULLY TESTED!")
