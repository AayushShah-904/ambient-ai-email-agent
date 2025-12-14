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