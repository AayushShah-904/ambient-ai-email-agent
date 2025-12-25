from langgraph.graph import StateGraph,START,END
from state import AgentState
from node import (  triage_node,
    check_route,
    react_route,
    ignore,
    respond_act,
    notify_human,
    react_model_node,
    react_tools_node,)


# from langgraph.checkpoint.memory import InMemorySaver
# from langgraph.prebuilt import create_react_agent
# from hitls import add_human_in_the_loop, DANGEROUS_TOOL_NAMES

# def build_agent(llm, tools):
#     safe_tools = []
#     for t in tools:
#         if t.name in DANGEROUS_TOOL_NAMES:
#             safe_tools.append(add_human_in_the_loop(t))
#         else:
#             safe_tools.append(t)

#     checkpointer = InMemorySaver()

#     agent = create_react_agent(
#         model=llm,
#         tools=safe_tools,
#         checkpointer=checkpointer,
#     )
#     return agent

#initilized graph
def graph_create()->StateGraph:
    graph=StateGraph(AgentState)

    #adding node
    graph.add_node("triage_node",triage_node)
    graph.add_node("ignore",ignore)
    graph.add_node("notify-human",notify_human)
    #graph.add_node("respond-act",respond_act)
    # ReAct nodes
    graph.add_node("react_model", react_model_node)
    graph.add_node("react_tools", react_tools_node)
    
    # #adding edge
    graph.add_edge(START,"triage_node")
    #adding route edge/conditional edge
     # Triage routing
    graph.add_conditional_edges(
        "triage_node",
        check_route,
        {
            "ignore": "ignore",
            "notify-human": "notify-human",
            "respond-act": "react_model",
        },
    )

    # ReAct loop wiring
    graph.add_conditional_edges(
        "react_model",
        react_route,
        {
            "react_tools": "react_tools",
            "react_end": END,
            "react_model": "react_model",  # in case it wants to think again
        },
    )
    graph.add_edge("react_tools", "react_model")

    # Terminal nodes
    graph.add_edge("ignore", END)
    graph.add_edge("notify-human", END)


    # graph.add_conditional_edges("triage_node",check_route)
    # graph.add_edge("ignore",END)
    # graph.add_edge("notify-human",END)
    # graph.add_edge("respond-act",END)

    

    return graph.compile()

app=graph_create()

def run_email_agent(subject: str, body: str) -> dict:
    """Run the LangGraph agent on one email and return triage + reply."""
    initial_state = {
        "mail": {
            "subject": subject,
            "body": body,
        }
    }
    result = app.invoke(initial_state)

    # Adapt these keys to whatever your state uses
    return {
        "triage": result.get("triage_category"),
        "reply": result.get("final_reply") ,
    }