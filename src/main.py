from graph import graph_create

workflow = graph_create()

output = workflow.invoke({
    "messages": [],
    "mail": {
        "subject": "Grammarly Premium Offer",
        "body": "Write better with Grammarly Premium - 50 percentage off.",
    },
    "tool_name": None,
    "tool_args": None,
    "final_reply": None,
})

print("\n=== FINAL STATE ===")
print("triage:", output["triage_category"])
print("final_reply:", output.get("final_reply"))
print("===================================================================================================")
print(output)

