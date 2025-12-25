import time
from langsmith import Client, evaluate
from graph import run_email_agent  # Assuming your agent is here

# --- STEP 1: PREPARE THE DATASET (Run once to be safe) ---
def ensure_dataset_exists():
    client = Client()
    dataset_name = "Golden_DataSet-2"
    
    # If dataset exists, we trust it (or you can delete it to force a refresh)
    if client.has_dataset(dataset_name=dataset_name):
        print(f"Dataset '{dataset_name}' found. Proceeding to evaluation.")
        return

    print(f"Dataset '{dataset_name}' not found. Creating it from your JSONL data...")
    dataset = client.create_dataset(
        dataset_name=dataset_name, 
        description="Email Triage Dataset"
    )

    # We load your specific JSONL structure
    # (I'm adding a small sample here based on your file)
    raw_data = [
        {"subject": "Meeting request for project kickoff", "body": "Hi, could we schedule...", "triage_label": "respond-act", "ideal_response": "Politely propose a specific time..."},
        {"subject": "URGENT: Production API returning 500 errors", "body": "Our customers are reporting...", "triage_label": "notify-human", "ideal_response": "Escalate to the human immediately..."},
        {"subject": "Newsletter: This week in tech", "body": "Welcome to this week in tech...", "triage_label": "ignore", "ideal_response": "Mark as non-actionable..."},
        # ... (LangSmith will handle the rest if you upload the full file)
    ]

    for row in raw_data:
        client.create_example(
            inputs={"subject": row["subject"], "body": row["body"]}, # INPUTS
            outputs={"ideal_response": row["ideal_response"], "triage_label": row["triage_label"]}, # OUTPUTS
            dataset_id=dataset.id
        )
    print("Dataset created successfully!")

# --- STEP 2: THE WRAPPER (Adapts Dataset -> Agent -> Judge) ---
def eval_wrapper(inputs):
    time.sleep(15)
    # 1. Extract Inputs (Matches your dataset keys)
    print(f"DEBUG - Actual Keys: {list(inputs.keys())}")
    
    subj = inputs["subject"]
    body_text = inputs["body"]

    # 2. Run your Agent
    # (This assumes run_email_agent returns {'reply': '...', 'triage': '...'})
    result = run_email_agent(subject=subj, body=body_text)
    

    # 3. Format Output for the Judge
    # Your Judge Prompt expects: 'output.model_output'
    return {
        "model_output": result["reply"],      # The text reply
        "triage_prediction": result["triage"] # The category
    }


# 1. Make sure data is ready
ensure_dataset_exists()

# 2. Run the specific experiment
print("Starting Evaluation...")
results = evaluate(
    eval_wrapper,
    data="Golden_DataSet-2",
    evaluators=[], # Empty because we use the "email_judge" in UI
    experiment_prefix="email-bot-v4",
    metadata={"version": "1.2", "model": "gemini-2.5-flash"}
) 
    
print("\nSucesssfully Evaluated")