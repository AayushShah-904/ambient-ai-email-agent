# Ambient Email Agent (Triage + ReAct + Evaluation)

This project is an email assistant built with **LangGraph**, **LLMs** (Gemini / Hugging Face), and **LangSmith**.  
It can:

- Classify incoming emails into:
  - `ignore`
  - `notify-human`
  - `respond-act`
- For `respond-act`, run a small **ReAct loop**:
  - Decide whether to call safe mock tools (like `read_calendar`)
  - Draft a reply using the tool results

Milestone 2 adds an automated **LLM-as-a-judge** evaluation framework in LangSmith that scores the quality of the agent’s replies (helpfulness, tone, instruction-following).[web:195][web:174]

---

## 1. Project structure



## 1. Project Structure

<img width="792" height="618" alt="image" src="https://github.com/user-attachments/assets/39b02f00-04f0-4ba5-8d08-fee41cb67360" />


---

## 2. LLM + LangSmith config (`config.py`)

- Configures chat models:
  - `gemini_ai_model()` → Google Gemini chat model.
  - `hugging_face_model()` → optional Hugging Face chat model.
- Loads API keys from `.env` (Gemini, Hugging Face, LangSmith).  
- With `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_API_KEY` set, all LangGraph runs are traced into LangSmith for debugging and evaluation.[web:195][web:188]

---

## 3. State definition (`state.py`)

Shared state that flows through the graph:


class AgentState(TypedDict):
messages: list[BaseMessage] # conversation history
mail: dict # {"subject": str, "body": str}
triage_category: Literal["ignore", "notify-human", "respond-act"]
tool_name: str | None # name of tool to call (inside ReAct)
tool_args: dict | None # arguments for that tool
final_reply: str | None # drafted reply for respond-act emails


- `messages` – chat history the ReAct loop reasons over.  
- `mail` – current email being processed.  
- `triage_category` – output of the triage step.  
- `tool_name` / `tool_args` – used only when a tool is called.  
- `final_reply` – final drafted reply for `respond-act` emails.

---

## 4. Triage node (`node.py` – `triage_node`)

- Reads `state["mail"]["subject"]` and `state["mail"]["body"]`.  
- Calls the LLM with a prompt that explains three categories:
  - **ignore** – newsletters, promos, low‑value notifications.
  - **notify-human** – important / urgent; user must see or decide.
  - **respond-act** – needs a reply or concrete action.
- Parses the model output into a `triage_category`.  
- `check_route` then routes:
  - `ignore` → `ignore` node → `END`
  - `notify-human` → `notify_human` node → `END`
  - `respond-act` → ReAct loop (starts at `react_model`)

Milestone 1 evaluates this triage step using `data/test_emails.csv` and a confusion matrix.[file:194]

---

## 5. ReAct loop nodes

### 5.1 `react_model_node`

- Reads `mail` and `messages` from state.  
- Builds a prompt that:
  - Describes available tools (`read_calendar`, `get_user_prefs`, etc.).  
  - Includes the email subject and body.
- LLM responds with either:
  - A **tool call** (JSON with `"tool"` and `"tool_args"`), or  
  - A **final reply** string.

Behavior:

- On tool call:
  - Sets `tool_name` / `tool_args` in state.
  - Routes to `react_tools_node`.
- On final reply:
  - Sets `final_reply`.
  - Clears `tool_name` / `tool_args`.
  - The graph ends.

### 5.2 `react_tools_node`

- Checks `state["tool_name"]`.  
- Calls the matching mock tool:
  - `"read_calendar"` → returns fixed free slots.  
  - `"get_user_prefs"` → returns fixed greeting/closing.  
- Appends a `[TOOL_RESULT] ...` message into `messages`.  
- Clears `tool_name` / `tool_args`.  
- Sends control back to `react_model_node` to continue reasoning.

This forms a standard ReAct loop inside LangGraph.[web:224]

---

## 6. Graph flow (`graph.py`) and `run_email_agent()`

- Uses `StateGraph(AgentState)` to wire nodes:

  - `START → triage_node`  
  - Conditional routing based on `triage_category`:
    - `ignore` → `ignore` → `END`
    - `notify-human` → `notify-human` → `END`
    - `respond-act` → `react_model` ReAct subgraph

- ReAct subgraph: `react_model ↔ react_tools` until a final reply is produced.

Helper function exposed in `graph.py`:

def run_email_agent(subject: str, body: str) -> dict:
"""Run the graph on a single email and return triage + reply."""
result = app.invoke({"mail": {"subject": subject, "body": body}})
return {
"triage": result.get("triage_category"),
"reply": result.get("final_reply"),
}


`run_email_agent` is used by the evaluation runner to process each dataset row.

---

## 7. Evaluation framework (Milestone 2)

### 7.1 Golden evaluation dataset

- File: `data/golden_set_emails.jsonl`  
- Contains 100+ realistic emails with:
  - `id`
  - `subject`
  - `body`
  - `triage_label` (expected triage category)
  - `ideal_response` (short description of the perfect reply / outcome)
- Uploaded to LangSmith as a Dataset (e.g. `Golden_DataSet`), mapping:
  - Inputs: `subject`, `body`
  - References: `ideal_response`, `triage_label`.[web:195]

### 7.2 LLM‑as‑a‑judge evaluator in LangSmith

Custom evaluator (e.g. `email_judge`) whose prompt tells the judge to read:

- Original email (subject + body)  
- Ideal outcome (`ideal_response`)  
- Assistant reply (`model_output`)

The judge returns three numeric scores (1–5):

- **helpfulness** – does the reply address the main request and move the task forward?  
- **tone** – is the tone polite and professionally appropriate?  
- **instruction_following** – how well does it match the ideal outcome (dates, confirmations, actions)?[web:174]

These three criteria are configured in the UI as 1–5 score fields.

### 7.3 Evaluation runner (`src/eval_runner.py`)

Connects dataset, agent, and judge:

from langsmith import Client
from langsmith.evaluation import evaluate
from graph import run_email_agent

client = Client()

def eval_wrapper(example):
subject = example.inputs["subject"]
body = example.inputs["body"]
result = run_email_agent(subject=subject, body=body)
return {
"model_output": result["reply"], # graded by email_judge
"triage_prediction": result["triage"] # optional extra field
}

results = evaluate(
eval_wrapper,
data="Golden_DataSet", # LangSmith dataset name
evaluators=["email_judge"], # LLM-as-a-judge evaluator
experiment_prefix="milestone-2",
)


Running this script:

- Executes the agent on all 100+ emails.  
- Calls the judge on each output.  
- Logs an experiment in LangSmith with per‑example and aggregate scores.[web:198][web:268]

You can inspect:

- Average `helpfulness` / `tone` / `instruction_following` per experiment.  
- Individual traces for low‑scoring cases.

This fulfills Milestone 2’s requirement for a fully automated evaluation framework.[web:188]

---

## 8. Notebooks

### 8.1 `01_triage_evaluation.ipynb`

- Loads `data/test_emails.csv`.  
- Runs each email through the graph.  
- Compares `triage_category` vs `label` and prints accuracy + confusion matrix (Milestone 1).

### 8.2 `02_react_agent.ipynb`

- Defines a few `respond-act` emails.  
- Runs the full graph and prints:
  - Input email
  - `triage_category`
  - `final_reply` from the ReAct loop  
- Used to visually inspect ReAct behavior.

### 8.3 `03_evaluation.ipynb`

- Optional notebook front‑end for Milestone 2:
  - Inspect the Golden dataset.  
  - Trigger `evaluate(...)` runs.  
  - Pull and visualize LangSmith metrics (histograms, averages).[web:188]

---

## 9. How to run

### 9.1 Install and set up

pip install -r requirements.txt

Create `.env`:

GOOGLE_API_KEY=your_gemini_key
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=ambient-email-agent

### 9.2 Run from terminal

python -m src.main


You should see:

- The triage result for the test email.  
- For `respond-act`, logs from the ReAct loop and the final drafted reply.

### 9.3 Run notebooks

jupyter lab notebooks/

- Open `01_triage_evaluation.ipynb` to test triage accuracy.  
- Open `02_react_agent.ipynb` to inspect ReAct behavior.  
- Open `03_evaluation.ipynb` to run and analyze LangSmith evaluations.
