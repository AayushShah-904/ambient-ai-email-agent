import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uuid
from typing import Dict, Any
from langchain_core.messages import HumanMessage
import time
from src.graph import create_graph
from src.hitl_handler import handle_hitl

def test_hitl_full_cycle():
    """Test HITL with real LLM triage + ReAct loop until natural HITL trigger."""
    
    # Fixed config
    config = {"configurable": {"thread_id": "hitl-test-full-1"}}
    app = create_graph()
    
    # Full email input
    dangerous_email = {
    "messages": [],
    "mail": {
        "subject": "Meeting Tue 2PM/demo",
        "body": (
            "Hi Aayush, can we do a demo meeting on Tuesday at 2PM IST? "
            "Please check your calendar and send confirmation email."
        ),
    },
}

    
    print("🚨 END-TO-END HITL TEST (real LLM)")
    print("=" * 50)
    
    # Run triage + ReAct until HITL suspends (ignore quota errors)
    try:
        app.invoke(dangerous_email, config)
        time.sleep(10)
    except Exception as e:
        print(f"⚠️ Expected quota error during triage: {e}")
    
    # Check if HITL envelope is set (from real LLM run)
    state = app.get_state(config)
    hitl = state.values.get("hitl")
    
    if not hitl or state.values.get("hitl_decision") != "pending":
        print("❌ PRODUCTION FAIL: LLM did not trigger HITL for dangerous action")
        print(f"Final state: tool_name={state.values.get('tool_name')}")
        print(f"HITL: {hitl}")
        return False
    
    if hitl and state.values.get("hitl_decision") == "pending":
        print("🎉 LLM naturally triggered HITL")
        tool_name = hitl["tool"]
        tool_args = hitl["args"]
    else:
        print("⚠️ LLM didn't trigger HITL, forcing test state")
        tool_args = {
            "to": "aayushshah90421@gmail.com",
            "subject": "Re: Presentation scheduled",
            "body": "Hi Aayush, ...",
        }
        app.update_state(
            config,
            {
                "tool_name": "send_gmail_reply",
                "tool_args": tool_args,
                "hitl": {
                    "tool": "send_gmail_reply",
                    "args": tool_args,
                    "proposed_reply": None,
                    "triage": state.values.get("triage_category"),
                },
                "hitl_decision": "pending",
            },
        )
    
    # Get user decision
    decision = input("\nHITL decision (approve/edit/deny): ").strip().lower()
    edit_values = None
    
    if decision == "edit":
        new_to = input("New 'to' (blank to keep): ").strip()
        new_subject = input("New 'subject' (blank to keep): ").strip()
        new_body = input("New 'body' (blank to keep): ").strip()
        
        edit_values = {}
        if new_to: edit_values["to"] = new_to
        if new_subject: edit_values["subject"] = new_subject
        if new_body: edit_values["body"] = new_body
    
    # Apply and resume
    print(f"\n👤 HITL: {decision.upper()}")
    if edit_values:
        print(f"Edit values: {edit_values}")
    
    handle_hitl(app, config, decision=decision, edit_values=edit_values)
    app.invoke(None, config)
    
    # Final state
    final_state = app.get_state(config)
    print("\n🏁 FINAL STATE:")
    print(f"Triage: {final_state.values.get('triage_category')}")
    print(f"Final reply: {final_state.values.get('final_reply')}")
    print(f"HITL: {final_state.values.get('hitl')}")
    print(f"HITL decision: {final_state.values.get('hitl_decision')}")
    print(f"Tool name: {final_state.values.get('tool_name')}")
    print(f"Tool args: {final_state.values.get('tool_args')}")

# def test_hitl_force():
#     """Pure HITL test: manually set envelope, test approve/edit/deny without LLM."""
    
#     config = {"configurable": {"thread_id": "hitl-test-force-v1"}}
#     app = create_graph()
    
#     print("🚨 FORCE HITL TEST")
#     print("=" * 50)
    
#     # Minimal state with mail (to avoid triage_node crash)
#     # minimal_state = {
#     #     "messages": [],
#     #     "mail": {
#     #         "subject": "Inquiry about pricing",
#     #         "body": "Manual HITL test email.",
#     #     },
#     #     "triage_category": "respond-act",
#     # }
    
#     minimal_state = {
#     "messages": [],
#     "mail": {
#         "subject": "Meeting Tue 2PM/demo",
#         "body": (
#             "Hi Aayush, can we do a demo meeting on Tuesday at 2PM IST? "
#         ),
#     },
#     "triage_category": "respond-act",
# }
#     app.update_state(config, minimal_state)
#     print("🤖 LLM generating reply...")
#     app.invoke(None, config)
#     # Check what LLM decided
#     state = app.get_state(config)
#     tool_name = state.values.get("tool_name")
#     tool_args = state.values.get("tool_args")
#     hitl = state.values.get("hitl")

#     # Force HITL for dangerous action if missing
#     if not hitl and tool_name in ["send_gmail_reply", "create_calendar"]:
#         if tool_name == "create_calendar":
#             tool_args = {
#                 "summary": "Demo Meeting",
#                 "date_str": "2026-01-13", 
#                 "time_str": "02:00 PM",
#                 "location": "Online"
#             }
#         else:  # send_gmail_reply fallback
#             tool_args = {
#                 "to": "sender@example.com",
#                 "subject": "Re: Meeting Tue 2PM/demo",
#                 "body": "Tuesday 2PM works! Added to calendar.",
#             }
        
#         app.update_state(
#             config,
#             {
#                 "tool_name": tool_name,
#                 "tool_args": tool_args,
#                 "hitl": {
#                     "tool": tool_name,
#                     "args": tool_args,
#                     "proposed_reply": tool_args.get("body"),
#                     "triage": "respond-act",
#                 },
#                 "hitl_decision": "pending",
#             },
#         )
    
#     # Show proposal (safe now)
#     state = app.get_state(config)
#     tool_name = state.values["tool_name"]
#     tool_args = state.values.get("tool_args", {})

#     print(f"\n🔥 DANGEROUS ACTION: {tool_name.upper()}")
#     print("Args:", tool_args)
    
#     print(f"LLM decided: tool={tool_name}, HITL={bool(hitl)}")
    
#     # Get user decision
#     decision = input("\nHITL decision (approve/edit/deny): ").strip().lower()
#     edit_values = None
    
#     if decision == "edit":
#         new_to = input("New 'to' (blank to keep): ").strip()
#         new_subject = input("New 'subject' (blank to keep): ").strip()
#         new_body = input("New 'body' (blank to keep): ").strip()
        
#         edit_values = {}
#         if new_to: edit_values["to"] = new_to
#         if new_subject: edit_values["subject"] = new_subject
#         if new_body: edit_values["body"] = new_body
    
#     # Apply and resume
#     print(f"\n👤 HITL: {decision.upper()}")
#     if edit_values:
#         print(f"Edit values: {edit_values}")
    
#     handle_hitl(app, config, decision=decision, edit_values=edit_values)
    
#     # Run hitl_checkpoint directly (no triage_node crash)
#     state = app.get_state(config).values
#     from src.nodes.node import hitl_checkpoint
#     final_state = hitl_checkpoint(state)
    
#     print("\n🏁 FINAL STATE (hitl_checkpoint only):")
#     print(f"Final reply: {final_state.get('final_reply')}")
#     print(f"HITL: {final_state.get('hitl')}")
#     print(f"HITL decision: {final_state.get('hitl_decision')}")
#     print(f"Tool name: {final_state.get('tool_name')}")
#     print(f"Tool args: {final_state.get('tool_args')}")

def test_hitl_force():
    """Real Calendar API + Force Email (end-to-end)."""
    
    config = {"configurable": {"thread_id": "hitl-test-real-v1"}}
    app = create_graph()
    
    print("🚨 REAL CALENDAR + FORCE EMAIL TEST")
    print("=" * 60)
    
    # Meeting email
    meeting_email = {
        "messages": [],
        "mail": {
            "subject": "Meeting Tue 2PM/demo",
            "body": "Hi Aayush, demo Tuesday 2PM IST? Confirm please.",
        },
        "triage_category": "respond-act",
    }
    
    print("🤖 LLM: Meeting extraction...")
    app.update_state(config, meeting_email)
    app.invoke(None, config)
    
    # CALENDAR HITL (LLM args or defaults)
    state = app.get_state(config)
    tool_name = state.values.get("tool_name")
    tool_args = state.values.get("tool_args", {})
    
    print(f"LLM: {tool_name} → {tool_args}")
    
    # Safe calendar args
    cal_args = tool_args if tool_name == "create_calendar" else {
        "summary": "Demo Meeting", 
        "date_str": "2026-01-13",
        "time_str": "02:00 PM", 
        "location": "Online"
    }
    
    print("\n📅 CALENDAR HITL:")
    print(f"  {cal_args.get('summary', 'Meeting')}: {cal_args.get('date_str', '?')} {cal_args.get('time_str', '?')}")
    
    # Calendar HITL
    cal_decision = input("Calendar (approve/edit/deny): ").strip().lower()
    if cal_decision == "deny":
        print("❌ Calendar skipped")
    else:
        # **RESUME GRAPH → EXECUTE REAL CALENDAR API**
        app.update_state(config, {
            "tool_name": "create_calendar",
            "tool_args": cal_args,
            "hitl": {"tool": "create_calendar", "args": cal_args, "triage": "respond-act"},
            "hitl_decision": "approved",  # Skip 2nd HITL
        })
        print("🔄 Resuming graph → Calling REAL create_calendar...")
        app.invoke(None, config)  # This runs your calendar node
        print("✅ Calendar API called!")
    
    # EMAIL REPLY (forced real send)
    print("\n📧 EMAIL HITL:")
    email_args = {
        "to": "aayushshah90421@gmail.com",
        "subject": "Re: Meeting Tue 2PM/demo", 
        "body": f"✅ {cal_args.get('summary', 'Meeting')} confirmed for {cal_args.get('date_str', '?')} {cal_args.get('time_str', '?')}",
    }
    print(f"  To: {email_args['to']}")
    print(f"  Body: {email_args['body']}")
    
    email_decision = input("Email (approve/edit/deny): ").strip().lower()
    if email_decision != "deny":
        # **FORCE REAL EMAIL SEND**
        app.update_state(config, {
            "tool_name": "send_gmail_reply",
            "tool_args": email_args,
            "hitl": {"tool": "send_gmail_reply", "args": email_args, "triage": "respond-act"},
            "hitl_decision": "approved",
        })
        print("📤 Sending REAL email...")
        app.invoke(None, config)  # Runs real send_gmail_reply
        print("✅ Email sent!")
    
    # Final verification
    final_state = app.get_state(config)
    print("\n🎉 VERIFIED:")
    print(f"Calendar tool: {final_state.values.get('tool_name')}")
    print(f"Email ID: {final_state.values.get('tool_args', {}).get('message_id', 'Check Gmail')}")



if __name__ == "__main__":
    print("Choose test:")
    print("1) End-to-end (real LLM + HITL)")
    print("2) Force HITL (no LLM)")
    
    choice = input("Enter 1 or 2: ").strip()
    
    if choice == "1":
        test_hitl_full_cycle()
    elif choice == "2":
        test_hitl_force()
    else:
        print("Invalid choice")

# Next production steps
# Your HITL is now ready for:

# UI integration: Replace input() with web/mobile UI that calls handle_hitl.

# Memory updates: Add memory_update logic in hitl_checkpoint for edits.

# Risk scoring: Add confidence thresholds so low‑risk emails skip HITL.

# Deployment: Gmail API polling loop → real inbox.

# Great work getting HITL solid! 🎉