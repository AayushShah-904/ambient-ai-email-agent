# 📬 Ambient AI Email Agent

> An autonomous, ambient AI agent that triages your inbox, drafts smart replies, and keeps you in control — powered by LangGraph and Google Gemini.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/framework-LangGraph-black.svg)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/frontend-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED.svg)](https://www.docker.com/)
[![Status](https://img.shields.io/badge/status-active-success.svg)]()

---

## 📖 Overview

The **Ambient AI Email Agent** is an intelligent inbox assistant that works quietly in the background. Unlike naive auto-responders, it uses **LLM-powered reasoning** and a **stateful graph workflow** to understand each email before acting.

It triages incoming messages, checks your Google Calendar for availability, drafts high-quality replies, and surfaces everything to you for approval — **nothing is ever sent automatically** without your consent.

---

## ✨ Features

- **🧠 Intelligent Triage** — Classifies every email as `ignore`, `notify-human`, or `respond-act`
- **🔁 ReAct Loop** — Reasoning + tool use to gather facts before drafting replies
- **📅 Calendar Integration** — Checks real availability and proposes meeting slots
- **🛑 Human-in-the-Loop (HITL)** — All drafts require your Approve / Edit / Deny before sending
- **💾 Persistent State** — PostgreSQL-backed checkpointing via LangGraph
- **📊 Evaluation Pipeline** — LLM-as-a-judge scoring for triage accuracy and reply quality
- **🔍 LangSmith Tracing** — Full observability for every agent run
- **🐳 Docker Ready** — One-command local deployment with Docker Compose

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     User (Browser)                      │
│                   Streamlit Frontend                    │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP
┌────────────────────────▼────────────────────────────────┐
│                  FastAPI Backend                        │
│           /scan-and-draft  /approve-action              │
└────────┬───────────────────────────┬────────────────────┘
         │                           │
┌────────▼────────┐       ┌──────────▼──────────┐
│   LangGraph     │       │   PostgreSQL DB      │
│   Workflow      │       │   (Checkpointing)    │
│                 │       └─────────────────────┘
│  triage_node    │
│      ↓          │       ┌─────────────────────┐
│  react_model    │──────►│   Google APIs        │
│      ↓          │       │  Gmail + Calendar    │
│  hitl_checkpoint│       └─────────────────────┘
└─────────────────┘
```

### Key Components

| Layer | Technology | Role |
|---|---|---|
| **Orchestration** | LangGraph 0.2 | Stateful workflow graph |
| **LLM** | Google Gemini (via `langchain-google-genai`) | Triage, reasoning, drafting |
| **Backend** | FastAPI + Uvicorn | REST API + HITL endpoints |
| **Frontend** | Streamlit | Dashboard for review & approval |
| **Database** | PostgreSQL + psycopg3 | Graph state checkpointing |
| **Memory** | FAISS + SQLite | Embedding-based preference retrieval |
| **Observability** | LangSmith | Tracing, debugging, evaluation |
| **Auth** | Google OAuth 2.0 | Secure Gmail/Calendar access |

---

## 📁 Folder Structure

```
langgraph-email-assistant/
├── backend/
│   └── src/
│       ├── main.py            # FastAPI app & API routes
│       ├── graph.py           # LangGraph workflow definition
│       ├── state.py           # AgentState schema
│       ├── nodes/             # Triage, ReAct, HITL nodes
│       ├── tools/
│       │   ├── google_gmail.py
│       │   └── google_calendar.py
│       ├── eval_runner.py     # Evaluation pipeline
│       ├── hitl_handler.py    # Human-in-the-loop logic
│       └── config.py
├── frontend/
│   └── app.py                 # Streamlit UI
├── notebooks/
│   ├── 01_triage_test.ipynb   # Triage sandbox
│   └── 02_react_agent.ipynb   # ReAct agent sandbox
├── test/                      # Pytest test suite
├── data/                      # Sample emails & datasets
├── credentials/               # Google OAuth credentials (gitignored)
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── requirements.txt
├── .env.example
└── PROJECT_GUIDE.md
```

---

## 🚀 Getting Started

### Prerequisites

- Python **3.11+**
- Docker & Docker Compose (recommended)
- A Google Cloud project with **Gmail API** and **Google Calendar API** enabled
- Google OAuth 2.0 credentials (`credentials.json`)
- A **LangSmith** account (optional, for tracing)

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/langgraph-email-assistant.git
cd langgraph-email-assistant
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
# LLM
GOOGLE_API_KEY=your_gemini_api_key

# Google OAuth (for Gmail & Calendar access)
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret

# PostgreSQL (auto-configured in Docker)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/email_assistance_db

# LangSmith (optional)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_PROJECT=ambient-email-agent
```

> **Note**: Place your `credentials.json` from Google Cloud Console in the `credentials/` directory.

---

## ▶️ Running the App

### Option A: Docker Compose (Recommended)

One command spins up the full stack — backend, frontend, and PostgreSQL:

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| **Frontend (Streamlit)** | http://localhost:8501 |
| **Backend (FastAPI)** | http://localhost:8000 |
| **API Docs (Swagger)** | http://localhost:8000/docs |
| **Database** | localhost:5432 |

### Option B: Running Natively

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Start the Backend**

```bash
uvicorn backend.src.main:app --reload --host 0.0.0.0 --port 8000
```

**3. Start the Frontend** (new terminal)

```bash
streamlit run frontend/app.py --server.port 8501
```

**4. Open the app** at [http://localhost:8501](http://localhost:8501)

---

## 🔄 Workflow

```
1. User triggers scan via UI
        ↓
2. Backend fetches emails from Gmail API
        ↓
3. LangGraph: triage_node classifies email
        ↓
   ┌────┴─────────────────────────┐
ignore   notify-human         respond-act
   │         │                    │
 Skip    Notify user         ReAct loop:
                            - Reason about email
                            - Call tools (calendar)
                            - Draft reply
                                  │
                            hitl_checkpoint
                            (pause for approval)
                                  │
                        User: Approve / Edit / Deny
                                  │
                            Send via Gmail API
```

---

## 📊 Evaluation

Run the evaluation pipeline to measure agent quality:

```bash
python -m backend.src.eval_runner
```

| Metric | Description |
|---|---|
| **Triage Accuracy** | % of emails classified correctly vs. human labels |
| **Reply Quality** | LLM-as-a-judge score (helpfulness, tone, correctness) |
| **HITL Correctness** | Agent correctly pauses for dangerous/sensitive actions |
| **Latency** | End-to-end processing time per email |

---

## 🧪 Testing & Notebooks

Run the test suite:

```bash
pytest test/
```

Explore the sandbox notebooks for experimentation without running the full server:

- `notebooks/01_triage_test.ipynb` — Test email classification in isolation
- `notebooks/02_react_agent.ipynb` — Trace the agent's step-by-step reasoning

---

## 🛠️ Tech Stack

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Runtime |
| LangGraph | 0.2.62 | Workflow orchestration |
| LangChain | 0.3.15 | LLM abstractions & tools |
| `langchain-google-genai` | 2.0.8 | Gemini LLM integration |
| FastAPI | 0.115.6 | Backend REST API |
| Uvicorn | 0.34.0 | ASGI server |
| Streamlit | 1.41.1 | Frontend UI |
| PostgreSQL / psycopg3 | 3.2.3 | Graph state persistence |
| FAISS | 1.9.0 | Vector store for memory |
| LangSmith | 0.1.147 | Tracing & evaluation |
| Google API Client | 2.152.0 | Gmail & Calendar APIs |
| Pydantic | 2.10.5 | Data validation |
| Pytest | 8.3.4 | Testing |
| Docker | — | Containerization |

---
## 🤝 Contributing

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature/your-feature`
3. **Commit** your changes: `git commit -m 'feat: add your feature'`
4. **Push** to the branch: `git push origin feature/your-feature`
5. **Open** a Pull Request

Please follow the existing code style (`black` + `ruff`) and add tests for new functionality.

---

## 📄 License

This project is licensed under the MIT License. See [LICENSE](./LICENSE) for details.

---

<p align="center">Built with ☕ and LangGraph</p>
