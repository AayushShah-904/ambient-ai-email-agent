import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.graph import create_graph

# app = create_graph()
# initial_state = {
#     "mail": {"subject": "Meeting request for project kickoff", "body": "Hi, could we schedule a 60-minute kickoff meeting next week to discuss the new analytics project? I am free Tuesday or Wednesday afternoon. Let me know what works for you."},
#     "messages": []
# }

# print("✅ LLM ready!")
# print("Running full workflow...")


# config = {"configurable": {"thread_id": "test1"}}
# output = app.invoke(initial_state, config)
# print(output.get("final_reply"))

app = create_graph()
config = {"configurable": {"thread_id": "interactive_hitl_1"}}

def run_interactive_agent(mail):
    print("🚀 Starting ambient agent...")
    state = {"mail": mail, "messages": []}
    
    # Run until HITL or complete
    while True:
        result = app.invoke(state, config)
        
        if result.get("tool_name") == "send_gmail_reply":
            print("\n🚨 HITL: Draft for approval:")
            print(f"To: {result['tool_args']['to']}")
            print(f"Subject: {result['tool_args']['subject']}")
            print(f"Body:\n{result['tool_args']['body']}\n")
            
            # USER INPUT
            feedback = input("Approve? [y/n/edit]: ").strip().lower()
            
            if feedback == 'y':
                state = {"human_feedback": "approve"}
            elif feedback == 'n':
                state = {"human_feedback": "deny", "final_reply": "Cancelled by user"}
                break
            else:  # edit
                new_body = input("New body: ")
                state = {
                    "human_feedback": "edit",
                    "tool_args": {
                        **result["tool_args"],
                        "body": new_body
                    }
                }
        else:
            print(f"✅ Complete: {result.get('final_reply', 'Done')}")
            break
    
    print("Workflow finished!")

# Test
mail = {
    "subject": "Meeting request - urgent?",
    "body": "Can we meet tomorrow 2PM to discuss Q1 targets?"
}
run_interactive_agent(mail)
