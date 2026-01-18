# Running the Evaluation Script

## Prerequisites

1. **LangSmith API Key**: Make sure your `.env` file has:
   ```
   LANGSMITH_API_KEY=your_api_key_here
   LANGSMITH_TRACING=true
   ```

2. **Dependencies installed**: 
   ```powershell
   pip install -r requirements.txt
   ```

## How to Run

```powershell
# Make sure you're in the project root
cd f:\Computer\Project\langgraph-email-assistant - Copy

# Activate virtual environment
venv\Scripts\activate

# Run the evaluation
python backend\src\eval_runner.py
```

## What It Does

1. **Creates Dataset** (if not exists): Loads sample emails into LangSmith
2. **Runs Evaluation**: Tests your agent on each email
3. **Records Results**: Saves results to LangSmith for analysis

## Expected Output

```
============================================================
📊 EMAIL ASSISTANT EVALUATION
============================================================

✅ Dataset 'Golden_DataSet-2' found. Proceeding to evaluation.

🚀 Starting evaluation on dataset 'Golden_DataSet-2'...
This may take a few minutes depending on dataset size...

📧 Evaluating email: Meeting request for project kickoff...
✅ Triage: respond-act

📧 Evaluating email: URGENT: Production API returning 500 errors...
✅ Triage: notify-human

...

============================================================
✅ EVALUATION COMPLETED SUCCESSFULLY!
============================================================

📊 View results at: https://smith.langchain.com/
🔍 Look for experiments with prefix: 'email-assistant'
```

## Troubleshooting

**Error: "No module named 'langsmith'"**
- Run: `pip install langsmith`

**Error: "LANGSMITH_API_KEY not found"**
- Add your API key to `.env` file
- Get your key from: https://smith.langchain.com/settings

**Error: "Dataset not found"**
- The script automatically creates it on first run
- To recreate: Delete the dataset in LangSmith UI and run again

## Viewing Results

1. Go to https://smith.langchain.com/
2. Navigate to "Datasets" to see your test data
3. Navigate to "Experiments" to see evaluation results
4. Compare different runs to track improvements
