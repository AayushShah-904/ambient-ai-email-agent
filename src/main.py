from graph import graph_create

workflow = graph_create()

output = workflow.invoke({
    "messages": [],
    "mail": {
        "subject": "Meeting tomorrow?",
        "body": "Hi, can we meet at 3pm tomorrow? Thanks!"
        "",
    },
    "tomol_nae": None,
    "tool_args": None,
    "final_reply": None,
})

print("\n=== FINAL STATE ===")
print("triage:", output["triage_category"])
print("final_reply:", output.get("final_reply"))
print("===================================================================================================")
print(output)

