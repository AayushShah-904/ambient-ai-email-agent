import datetime
import re
import json
from langchain_core.prompts import PromptTemplate,ChatPromptTemplate
from langchain_core.messages import HumanMessage,AIMessage
from pydantic import Field,BaseModel
from state import AgentState
from config import gemini_ai_model
from tools import read_calendar, get_user_prefs
from typing import Literal,Annotated
from langchain_core.output_parsers import PydanticOutputParser

model_gemini=gemini_ai_model()
#model_hugging=hugging_face_model()


class Category(BaseModel):
    category: Annotated[Literal["ignore","notify-human","respond-act"],"The classification of the email based on the rules."]

parser=PydanticOutputParser(pydantic_object=Category)

prompt = PromptTemplate(template="""
("system", "You are an email categorization assistant."),
    ("human",
    Analyze the following email and categorize it.
    
    Subject: {subject}
    Body: {body}
    
    {format_instructions}
    
    DEFINITIONS:
    - "ignore": Newsletters, promotional offers, spam, or automated notifications.
    - "notify-human": Security alerts, urgent issues, emotional/complex topics, or emails requiring manual authority.
    - "respond-act": Scheduling requests, simple information queries, or casual team chats that you can handle.

    FEW-SHOT EXAMPLES:
    1. Subject: "50% Off Shoes" | Body: "Buy now!" -> category: "ignore"
    2. Subject: "Server Down" | Body: "Production API 500 error" -> category: "notify-human"
    3. Subject: "Lunch?" | Body: "Free for lunch Tuesday?" -> category: "respond-act"
    4. Subject: "Suspicious Login" | Body: "New sign-in from Russia" -> category: "notify-human"
    
    IMPORTANT RULES:
    1. Return ONLY the JSON object. 
    2. Do NOT add any preamble.
""",
input_variables=["subject", "body"],
partial_variables={"format_instructions": parser.get_format_instructions()}
)

reAct_prompt = """
You are Aayush's Executive AI Assistant. Current Date/Time: {current_time_str}

TOOLS:
- read_calendar() -> Checks availability.
- get_user_prefs() -> Gets signature/preferences.

### RESPONSE GUIDELINES (Maximize Politeness):
1. **Tone:** Professional yet warm. Use "Hi" for casual/internal, "Dear" for formal.
2. **Clarity:** Confirm the specific date and time explicitly (e.g., "Monday, Dec 25th at 2 PM").
3. **Closing:** ALWAYS sign off exactly as: "Best regards, Aayush's AI Assistant".

### EXECUTION RULES:
1. If using a tool, return JSON ONLY.
2. If answering, write the final email text directly.
"""
# Get current time for the prompt
#current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # reAct_prompt = """
    # You are an email assistant that can both THINK and ACT.
    # Current Date/Time: {current_time_str}

    # TOOLS YOU CAN USE:
    # - read_calendar() -> returns available meeting slots
    # - add_calendar_event(summary, date_str, time_str, location) -> adds a new event
    # - get_user_prefs() -> returns user preferences

    # ### CRITICAL RULES FOR EVENT EXTRACTION:
    # When you decide to call `add_calendar_event`, you must calculate arguments strictly:
    # 1. RELATIVE DATES: If email says "next Tuesday", calculate the EXACT YYYY-MM-DD based on {current_time_str}.
    # 2. VAGUE TIMES:
    #    - "Morning" -> "10:00 AM"
    #    - "Afternoon" -> "02:00 PM"
    #    - "Evening" -> "06:00 PM"
    # 3. CONFLICTS: If multiple days are offered ("Tue or Wed"), ALWAYS pick the FIRST option.
    # 4. LOCATION: If missing, default to "Online".

    # ### YOUR JOB:
    # 1. Read the email.
    # 2. Decide if you need to CALL A TOOL or ANSWER directly.
    # 3. If using a tool, respond with this EXACT JSON format:
    #    {{
    #      "tool": "add_calendar_event",
    #      "args": {{
    #         "summary": "Meeting with Bob",
    #         "date_str": "2025-12-25",
    #         "time_str": "02:00 PM",
    #         "location": "Online"
    #      }}
    #    }}
    # 4. If you are ready to ANSWER (or if no event was found), respond with plain natural language.

    # Never send both JSON and natural language in the same response.
    # """
# node function
def triage_node(state:AgentState)->AgentState:
    mail=state['mail']

    chain=prompt|model_gemini|parser
    result_obj=chain.invoke({"subject":mail['subject'],"body":mail['body']})
    #Extract the actual string from the object
    category_str=result_obj.category

    print(f"✅ Triage: {category_str}")

    return {"triage_category":category_str}


def check_route(state: AgentState)->Literal["ignore","notify-human","respond-act"]:

    if state["triage_category"]=="ignore":
        return "ignore"
    elif state["triage_category"]=="notify-human":
        return "notify-human"
    elif state["triage_category"]=="respond-act":
        return "respond-act"
    else:
        return "notify-human"        #safe 
    
def react_route(state: AgentState):

    if state.get("tool_name"):
        return "react_tools"
    elif state.get("final_reply"):
        return "react_end"
    else:
        return "react_model"
    
    
def react_model_node(state: AgentState) -> AgentState:
    mail = state["mail"]
    messages = state["messages"].copy()
    
    # --- 1. ONLY ADD INSTRUCTIONS ON THE FIRST TURN ---
    if not messages:
        # Get REAL current time
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Inject it into the prompt
        system_prompt = f"""
            You are an email assistant. Current Time: {now_str}

            TOOLS:
            - read_calendar()
            - get_user_prefs()

            RULES:
            1. TIME: If email says "tomorrow" or "Tuesday", calculate the date based on {now_str}.
            2. FORMAT: 
            - If using a tool, output JSON ONLY: {{"tool": "...", "args": {{...}}}}
            - If answering, write plain natural language. Do NOT output JSON.
        """
        user_content = f"{system_prompt}\n\nEMAIL:\nSubject: {mail['subject']}\nBody: {mail['body']}\n"
        messages.append(HumanMessage(content=user_content))

 
    try:
        resp = model_gemini.invoke(messages)
        text = resp.content.strip()
    except Exception as e:
        print("⚠️ Gemini failed:", e)
        fallback = "I received your email and will get back to you."
        return {
            "messages": messages + [AIMessage(content=fallback)],
            "final_reply": fallback,
            "tool_name": None, "tool_args": None
        }
    
    tool_name = None
    tool_args = None
    
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    
    if json_match:
        try:
            obj = json.loads(json_match.group(0))
            if "tool" in obj:
                tool_name = obj.get("tool")
                tool_args = obj.get("args", {})
        except Exception:
            pass


    if tool_name:
        print(f"🔧 ReAct: Tool requested -> {tool_name}")
        return {
            "messages": messages + [AIMessage(content=text)],
            "tool_name": tool_name,
            "tool_args": tool_args,
        }
    else:
        print("💬 ReAct: Final reply generated")
        return {
            "messages": messages + [AIMessage(content=text)],
            "tool_name": None,
            "tool_args": None,
            "final_reply": text,
        }    

def react_tools_node(state: AgentState) -> AgentState:
    tool_args = state.get("tool_args") or {}
    messages = state["messages"].copy()

    if state["tool_name"] == "read_calendar":
        result = read_calendar()
        hint = "\n(HINT: Pick the first available slot that fits the user's request and propose it directly. Do not ask the user to pick if you can suggest one.)"
        content = f"[TOOL_RESULT] read_calendar: {result} {hint}"
    elif state["tool_name"] == "get_user_prefs":
        result = get_user_prefs()
        content = f"[TOOL_RESULT] get_user_prefs: {result}"
    else:
        # Unknown tool → do nothing, let model try again
        result = {"error": f"unknown tool: {state['tool_name']}"}
        content = f"[ERROR] {result}"

    messages.append(HumanMessage(content=content))

    print(f"Tool executed: {state['tool_name']} -> {result}")

    return {
        "messages": messages,
        "tool_name": None,
        "tool_args": None,
    }


def ignore(state:AgentState)->AgentState:
    print("Ignored email (newsletter/promo).")
    return state


def notify_human(state:AgentState)->AgentState:
    print("Notifying human: important email.")
    return state

def respond_act(state:AgentState)->AgentState:
    print("Initiating React_Agent_Loop")
    return state

