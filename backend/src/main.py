import os
import time
import uuid
import asyncio
import re
from bs4 import BeautifulSoup 
import requests
from typing import Optional, List, Literal
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from psycopg_pool import AsyncConnectionPool
from psycopg import AsyncConnection
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from fastapi.middleware.cors import CORSMiddleware

        
from backend.src.db_init import init_db
from backend.src.tools.google_gmail import fetch_emails,send_reply,mark_as_processed,apply_gmail_label,get_gmail_service
from backend.src.tools.google_calendar import generate_meeting_response_llm,extract_event_details_llm,book_best_slot,generate_general_llm,delete_calendar_event
from backend.src.tools.auth import SCOPES, get_google_client_config
from backend.src.graph import create_graph

load_dotenv()

# Allow OAuth to proceed over HTTP (local development) and relaxed scopes
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPES"] = "1"

DB_URI = os.getenv("DATABASE_URL")
if not DB_URI:
    raise ValueError("DATABASE_URL environment variable is not set in the environment.")
if DB_URI.startswith("postgres://"):
    DB_URI = DB_URI.replace("postgres://", "postgresql://", 1)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

class ScanRequest(BaseModel):
    """Request format for scanning user's inbox"""
    userid: str = Field(..., min_length=1, max_length=100, description="User identifier")
    
    class Config:
        json_schema_extra = {
            "example": {
                "userid": "john.doe"
            }
        }

class ApprovalActionRequest(BaseModel):
    """User's decision on AI-generated email draft"""
    thread_id: str = Field(..., pattern=r"^thread_[a-f0-9]{12}$", description="Thread identifier")
    action: Literal["approve", "edit", "deny"] = Field(..., description="Action to perform")
    user_id: str = Field(..., min_length=1, max_length=100, description="User identifier")
    edited_text: Optional[str] = Field(None, max_length=10000, description="Edited email text")
    
    class Config:
        json_schema_extra = {
            "example": {
                "thread_id": "thread_a1b2c3d4e5f6",
                "action": "approve",
                "user_id": "john.doe",
                "edited_text": None
            }
        }

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Sets up the database pool and LangGraph agent when the app starts.
    This runs once at startup and cleans up automatically on shutdown.
    """
    # 1. Run migrations/setup with dedicated conn string manager (autocommit-safe)
    async with AsyncPostgresSaver.from_conn_string(DB_URI) as setup_checkpointer:
        await setup_checkpointer.setup()

    # 2. Run the main pool for endpoint queries
    async with AsyncConnectionPool(conninfo=DB_URI, max_size=20) as pool:
        await init_db(pool)

        checkpointer = AsyncPostgresSaver(pool)
        
        # Make pool and agent available to all endpoints
        app.state.db_pool = pool 
        app.state.agent = create_graph(checkpointer=checkpointer)
        
        print("Database Pool and Graph Initialized")
        yield

app = FastAPI(title="Ambient Email Agent", lifespan=lifespan)

# Add CORS middleware to allow the Streamlit frontend to communicate with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_db(request: Request):
    """Every API request gets its own database connection from the pool"""
    pool = request.app.state.db_pool
    async with pool.connection() as conn:
        yield conn

@app.get("/auth/login")
async def login():
    """Redirects user to Google's OAuth consent screen"""
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(get_google_client_config(), scopes=SCOPES)
    flow.redirect_uri = os.getenv("BACKEND_URL", "http://localhost:8000") + "/auth/callback"
    auth_url, _ = flow.authorization_url(access_type='offline', prompt='consent')
    return RedirectResponse(auth_url)

@app.get("/auth/callback")
async def callback(code: str, request: Request, db=Depends(get_db)):
    """
    Google sends the user back here after they approve access.
    We exchange the auth code for tokens and save them to the database.
    """
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(get_google_client_config(), scopes=SCOPES)
    flow.redirect_uri = os.getenv("BACKEND_URL", "http://localhost:8000") + "/auth/callback"
    flow.fetch_token(code=code)
    
    creds = flow.credentials
    user_info_resp = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {creds.token}"}
    )
    if not user_info_resp.ok:
        raise HTTPException(status_code=400, detail=f"Failed to fetch user info: {user_info_resp.text}")
    
    user_info = user_info_resp.json()
    email = user_info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email address not returned by Google. Ensure scopes include email.")
    
    # Use the part before @ as the user's identifier
    user_id = email.split('@')[0]
    
    # Save or update user's tokens in the database
    await db.execute(
        """INSERT INTO user_tokens (user_id, access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE SET 
           access_token = EXCLUDED.access_token, 
           refresh_token = EXCLUDED.refresh_token,
           expiry = EXCLUDED.expiry""",
        (user_id, creds.token, creds.refresh_token, creds.token_uri, 
         creds.client_id, creds.client_secret, str(creds.scopes), creds.expiry)
    )
    
    # Send user back to the Streamlit UI with their user ID
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8501")
    return RedirectResponse(f"{frontend_url}/?user_id={user_id}")




def strip_html_tags(html_text: str) -> str:
    """Convert HTML to plain text for fallback."""
    soup = BeautifulSoup(html_text, 'html.parser')
    return soup.get_text()
    
@app.post("/v1/scan-and-draft")
async def scan_and_draft(request: ScanRequest, db: AsyncConnection = Depends(get_db)):
    try:
        emails = await fetch_emails(db, request.userid)
        if not emails:
            return {"status": "empty", "message": "No new emails."}
        
        # Limit to the first 2 emails as requested
        emails_to_process = emails[:1]
        processed_results = []

        for email in emails_to_process:
            # Create a unique thread ID for each email
            thread_id = f"thread_{uuid.uuid4().hex[:12]}"
            config = {"configurable": {"thread_id": thread_id, "db": db}}
            event_id = None
            
            initial_state = {
                "mail": email, 
                "userid": request.userid,
            }
            
            # 1. Run the AI Graph for this specific email
            await app.state.agent.ainvoke(initial_state, config=config)
            print(f"DEBUG: Email Subject: {email['subject']}")
            # 2. Get the results for this email
            state = await app.state.agent.aget_state(config)
            category = state.values.get("triage_category")
            draft = state.values.get("final_reply")

            # 3. Handle Automation Categories (Ignore/Notify)
            if category == "ignore":
                await mark_as_processed(db, request.userid, email['id'])
                processed_results.append({
                    "thread_id": thread_id,
                    "status": "completed",
                    "category": "ignore",
                    "subject": email['subject']
                })
                continue

            if category == "notify-human":
                await apply_gmail_label(db, request.userid, email['id'])
                processed_results.append({
                    "thread_id": thread_id,
                    "status": "completed",
                    "category": "notify-human",
                    "subject": email['subject']
                })
                continue

            # 4. Handle Respond-Act (Meeting Logic) - UPDATED
            if category == "respond-act":
                # 1. Fetch full message
                service = await get_gmail_service(db, request.userid)
                loop = asyncio.get_running_loop()
                full_msg = await loop.run_in_executor(
                    None,
                    lambda: service.users().messages().get(
                        userId='me', id=email['id'], format='full'
                    ).execute()
                )
                
                # 2. Extract details
                event_details = await extract_event_details_llm(email['body'], email['subject'])
                
                # 🟢 NEW: Check if slots actually exist and are not empty
                # If the LLM returns no slots, it's not a meeting email!
                has_valid_slots = event_details and event_details.get('slots') and len(event_details.get('slots')) > 0
                
                current_event_id = None
                
                if has_valid_slots:
                    # Proceed with booking logic
                    success, slot, event_id, reasons = await book_best_slot(db, request.userid, event_details)
                    current_event_id = event_id if success else None
                    
                    draft = await generate_meeting_response_llm(
                        full_msg=full_msg,
                        event_details=event_details,
                        booked_slot=slot if success else None,
                        calendar_event_id=current_event_id,
                        rejection_reasons=None if success else (reasons or ["No available slots"])
                    )
                else:
                    # 🟢 CORRECT FALLBACK: This email (like Infosys) is now treated as general
                    draft = await generate_general_llm(full_msg)
                # Update state with the final draft text
                await app.state.agent.aupdate_state(config, {
                    "final_reply": draft,
                    "event_id": event_id, 
                    "mail": email 
                })

                processed_results.append({
                    "thread_id": thread_id,
                    "status": "waiting_for_approval",
                    "category": category,
                    "sender": email['sender'],
                    "subject": email['subject'],
                    "proposed_reply_html": draft,  
                    "proposed_reply_plain": strip_html_tags(draft), 
                    "event_id": event_id
                })


        return {"status": "success", "results": processed_results}
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/approve-action")
async def approve_action(data: ApprovalActionRequest, db: AsyncConnection = Depends(get_db)):
    config = {"configurable": {"thread_id": data.thread_id}}
    
    try:
        # 1. Get the current state BEFORE resuming the graph
        # This ensures we get the event_id that was saved during scan-and-draft
        current_state = await app.state.agent.aget_state(config)
        event_id = current_state.values.get("event_id")
        email_data = current_state.values.get("mail")
        
        # 2. Record the human decision
        state_update = {"hitl_decision": data.action}
        if data.action == "edit" and data.edited_text:
            state_update["final_reply"] = data.edited_text
            
        await app.state.agent.aupdate_state(config, state_update)
        
        # 3. Resume the Graph
        config["configurable"]["db"] = db
        await app.state.agent.ainvoke(None, config=config)
        
        # 4. Handle the "Deny" Cleanup
        if data.action.lower() == "deny":
            if event_id:
                await delete_calendar_event(db, data.user_id, event_id)
                print(f"DEBUG: Successfully triggered deletion for {event_id}")
            
            await mark_as_processed(db, data.user_id, email_data['id'])
            return {"status": "success", "message": "Event deleted and mail read."}

        # 5. Handle Approve/Edit
        # (Retrieve fresh values if ainvoke changed them, otherwise use existing)
        final_state = await app.state.agent.aget_state(config)
        reply_content = final_state.values.get("final_reply")
        
        if data.action in ["approve", "edit"]:
            # Check for "Re:" prefix
            original_subject = email_data.get('subject', 'No Subject')
            final_subject = original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}"
            formatted_reply = reply_content.replace("\n", "<br>")
            
            await send_reply(
                db=db,
                user_id=data.user_id,
                to_email=email_data['sender'],
                subject=final_subject,
                message_text=formatted_reply
            )

        await mark_as_processed(db, data.user_id, email_data['id'])
        return {"status": "success", "message": "Process completed successfully."}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))