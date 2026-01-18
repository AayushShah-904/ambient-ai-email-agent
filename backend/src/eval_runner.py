"""
Email Assistant Evaluation Runner
Evaluates the email assistant using LangSmith datasets
"""
import json
import asyncio
from langsmith import Client
from langsmith.evaluation import evaluate
from backend.src.graph import create_graph
from langgraph.checkpoint.memory import MemorySaver

# Initialize checkpointer
checkpointer = MemorySaver()

# --- STEP 1: PREPARE THE DATASET ---
def ensure_dataset_exists():
    """Create LangSmith dataset from sample data if it doesn't exist"""
    client = Client()
    dataset_name = "Golden_DataSet-2"
    
    # Check if dataset already exists
    if client.has_dataset(dataset_name=dataset_name):
        print(f"✅ Dataset '{dataset_name}' found. Proceeding to evaluation.")
        return dataset_name
    
    print(f"📝 Dataset '{dataset_name}' not found. Creating it from sample data...")
    
    # Create new dataset
    dataset = client.create_dataset(
        dataset_name=dataset_name, 
        description="Email Triage Dataset for AI Assistant Evaluation"
    )
    
    # Sample data based on your email types
    raw_data = [
        {
            "subject": "Meeting request for project kickoff", 
            "body": "Hi, could we schedule a 60-minute kickoff meeting next week to discuss the new analytics project? I am free Tuesday or Wednesday afternoon. Let me know what works for you.",
            "triage_label": "respond-act", 
            "ideal_response": "Politely propose a specific time and check calendar availability"
        },
        {
            "subject": "URGENT: Production API returning 500 errors", 
            "body": "Our customers are reporting widespread 500 errors from the /api/users endpoint. This started 15 minutes ago and is affecting all regions. Please investigate immediately.",
            "triage_label": "notify-human", 
            "ideal_response": "Escalate to the human immediately with high priority alert"
        },
        {
            "subject": "Newsletter: This week in tech", 
            "body": "Welcome to this week in tech news! Here are the top stories: AI breakthroughs, new programming languages, and cloud computing trends...",
            "triage_label": "ignore", 
            "ideal_response": "Mark as non-actionable newsletter content"
        },
        {
            "subject": "Important Meeting Tomorrow",
            "body": "Hi, can we schedule a meeting for tomorrow at 3 PM? Please send a confirmation.",
            "triage_label": "respond-act",
            "ideal_response": "Check calendar and confirm availability or suggest alternative time"
        },
        {
            "subject": "Question about pricing",
            "body": "Hi, I wanted to ask about your Q4 pricing. Can you send me the latest price list?",
            "triage_label": "respond-simple",
            "ideal_response": "Acknowledge and provide pricing information or mention it will be sent"
        }
    ]
    
    # Add examples to dataset
    for row in raw_data:
        client.create_example(
            inputs={"subject": row["subject"], "body": row["body"]},
            outputs={"ideal_response": row["ideal_response"], "triage_label": row["triage_label"]},
            dataset_id=dataset.id
        )
    
    print(f"✅ Dataset created successfully with {len(raw_data)} examples!")
    return dataset_name


# --- STEP 2: EVALUATION WRAPPER (Synchronous wrapper for async graph) ---
def eval_wrapper(inputs):
    """
    Wrapper function that adapts dataset inputs to agent and returns outputs for evaluation
    This runs synchronously but handles the async graph internally
    """
    print(f"📧 Evaluating email: {inputs['subject'][:50]}...")
    
    # Extract inputs from dataset
    subject = inputs.get("subject", "")
    body = inputs.get("body", "")
    
    # Prepare initial state for the graph
    initial_state = {
        "mail": {"subject": subject, "body": body},
        "messages": []
    }
    
    # Create config with unique thread ID for each evaluation
    import uuid
    config = {
        "configurable": {
            "thread_id": f"eval-{uuid.uuid4().hex[:8]}"
        }
    }
    
    try:
        # Create and run the graph
        app = create_graph()
        result = app.invoke(initial_state, config)
        
        # Extract outputs for evaluation
        model_output = result.get("final_reply", "No reply generated")
        triage_prediction = result.get("triage_category", "unknown")
        
        print(f"✅ Triage: {triage_prediction}")
        
        return {
            "model_output": model_output,
            "triage_prediction": triage_prediction
        }
        
    except Exception as e:
        print(f"❌ Error during evaluation: {e}")
        return {
            "model_output": f"ERROR: {str(e)}",
            "triage_prediction": "error"
        }


# --- STEP 3: RUN EVALUATION ---
def run_evaluation():
    """Main function to run the LangSmith evaluation"""
    print("\n" + "=" * 60)
    print("📊 EMAIL ASSISTANT EVALUATION")
    print("=" * 60 + "\n")
    
    # Step 1: Ensure dataset exists
    dataset_name = ensure_dataset_exists()
    
    # Step 2: Run evaluation
    print(f"\n🚀 Starting evaluation on dataset '{dataset_name}'...")
    print("This may take a few minutes depending on dataset size...\n")
    
    try:
        results = evaluate(
            eval_wrapper,
            data=dataset_name,
            evaluators=[],  # Add custom evaluators here if needed
            experiment_prefix="email-assistant",
            metadata={
                "version": "2.0",
                "model": "gemini-2.5-flash",
                "architecture": "async-langgraph"
            }
        )
        
        print("\n" + "=" * 60)
        print("✅ EVALUATION COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        print(f"\n📊 View results at: https://smith.langchain.com/")
        print(f"🔍 Look for experiments with prefix: 'email-assistant'\n")
        
        return results
        
    except Exception as e:
        print(f"\n❌ Evaluation failed: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure LANGSMITH_API_KEY is set in your .env file")
        print("2. Verify your LangSmith project is configured")
        print("3. Check that the graph can run successfully")
        return None


if __name__ == "__main__":
    # Run the evaluation
    run_evaluation()