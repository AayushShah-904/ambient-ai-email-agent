from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage,AIMessage
from pydantic import Field,BaseModel
from state import AgentState
from config import gemini_ai_model,hugging_face_model
from tools import read_calendar, get_user_prefs
from typing import Literal,Annotated
from langchain_core.output_parsers import PydanticOutputParser

model_gemini=gemini_ai_model()
model_hugging=model_gemini


class Category(BaseModel):
    category: Annotated[Literal["ignore","notify-human","respond-act"],"The classification of the email based on the rules."]

parser=PydanticOutputParser(pydantic_object=Category)

prompt = PromptTemplate(template="""
("system", "You are an email categorization assistant."),
    ("human",
    Analyze the following email and categorize it.
    
    Subject: {subject}
    Body: {body}
    
    {format_instructions}  <-- ENSURE THIS IS INCLUDED
    
    IMPORTANT RULES:
    1. Return ONLY the JSON object. 
    2. Do NOT add any preamble like "Here is the JSON".
    3. Do NOT add any explanation after the JSON.
    4. Do NOT use Markdown formatting (no ```json blocks). Just raw JSON.
""",
input_variables=["subject", "body"],
    
partial_variables={"format_instructions": parser.get_format_instructions()}
)

reAct_prompt = """
You are an email assistant that can both THINK and ACT.

TOOLS YOU CAN USE:
- read_calendar() -> returns available meeting slots
- get_user_prefs() -> returns user preferences like greeting and closing

Your job:
1. Read the email.
2. Decide if you need to CALL A TOOL or if you can ANSWER directly.
3. If using a tool, respond with a JSON object ONLY:
   {"tool": "read_calendar", "args": {}}
   or
   {"tool": "get_user_prefs", "args": {}}
4. If you are ready to ANSWER, respond with plain natural language (no JSON).

Never send both JSON and natural language in the same response.
"""

# node function
def triage_node(state:AgentState)->AgentState:
    mail=state['mail']

    chain=prompt|model_hugging|parser
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

    # Build a single user message including email
    user_content = (
        f"{reAct_prompt}\n\n"
        f"EMAIL:\nSubject: {mail['subject']}\nBody: {mail['body']}\n"
    )
    messages.append(HumanMessage(content=user_content))

    resp = model_gemini.invoke(messages)
    text = resp.content.strip()

    tool_name = None
    tool_args = None

    if text.startswith("{") and "tool" in text:
        try:
            import json
            obj = json.loads(text)
            tool_name = obj.get("tool")
            tool_args = obj.get("args", {})
        except Exception:
            tool_name = None
            tool_args = None

    if tool_name:
        # LLM wants to call a tool → set tool_name/tool_args, continue loop
        print(f"🔧 ReAct: model requested tool {tool_name} with args {tool_args}")
        return {
            "messages": messages + [AIMessage(content=text)],
            "tool_name": tool_name,
            "tool_args": tool_args,
        }
    else:
        # LLM produced a final answer
        print("💬 ReAct: model produced final reply")
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
    elif state["tool_name"] == "get_user_prefs":
        result = get_user_prefs()
    else:
        # Unknown tool → do nothing, let model try again
        result = {"error": f"unknown tool: {state['tool_name']}"}

    messages.append(
        HumanMessage(content=f"[TOOL_RESULT] {state['tool_name']}: {result}")
    )

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

