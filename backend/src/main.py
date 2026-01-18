import os
import time
import uuid
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

from backend.src.tools.google_gmail import fetch_emails,send_reply,mark_as_processed,get_sender_and_subject,apply_gmail_label
from backend.src.tools.google_calendar import generate_meeting_response_llm,extract_event_details_llm,book_best_slot,generate_general_llm
from backend.src.tools.auth import get_user_service, SCOPES
from backend.src.graph import create_graph

load_dotenv()

DB_URI = os.getenv("DATABASE_URL")
CLIENT_SECRETS_FILE = "credentials/credentials.json"

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
    async with AsyncConnectionPool(conninfo=DB_URI, max_size=20) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup() 
        
        # Make pool and agent available to all endpoints
        app.state.db_pool = pool 
        app.state.agent = create_graph(checkpointer=checkpointer)
        
        print("Database Pool and Graph Initialized")
        yield

app = FastAPI(title="Ambient Email Agent", lifespan=lifespan)

async def get_db(request: Request):
    """Every API request gets its own database connection from the pool"""
    pool = request.app.state.db_pool
    async with pool.connection() as conn:
        yield conn

@app.get("/auth/login")
async def login():
    """Redirects user to Google's OAuth consent screen"""
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
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
    flow = Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = os.getenv("BACKEND_URL", "http://localhost:8000") + "/auth/callback"
    flow.fetch_token(code=code)
    
    creds = flow.credentials
    user_info = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {creds.token}"}
    ).json()
    
    # Use the part before @ as the user's identifier
    user_id = user_info.get("email").split('@')[0]
    
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

@app.post("/v1/scan-and-draft")
async def scan_and_draft(request: ScanRequest, db: AsyncConnection = Depends(get_db)):
    """
    This is the main email processing endpoint. It:
    1. Fetches the latest unread email from Gmail
    2. Asks the AI to classify it (ignore/notify/respond)
    3. If it needs a response, generates a draft for human approval
    """
    # Create a unique thread ID so we can track this email's state in the database
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        draft = None
        emails = await fetch_emails(db, request.userid)
        if not emails:
            return {"status": "empty", "message": "No new emails."}
        
        # Feed the email into the AI agent
        initial_state = {
            "mail": emails[0], 
            "userid": request.userid,
        }
        
        # Pass db through config, not state (AsyncConnection can't be serialized)
        config["configurable"]["db"] = db
        
        await app.state.agent.ainvoke(initial_state, config=config)
        
        # Check what the AI decided to do
        state = await app.state.agent.aget_state(config)
        category = state.values.get("triage_category")
        draft = None
        
        if category == "ignore":
            # Spam or newsletter - just mark it read
            # Action handled by 'ignore' node in graph
            await mark_as_processed(db, request.userid, emails[0]['id'])
            return {
                "status": "completed",
                "category": "ignore",
                "message": "Email identified as spam/newsletter and marked as read.",
                "subject": emails[0]['subject']
            }

        if category == "notify-human":
            # Important email that needs human attention - add a label
            # Action handled by 'notify-human' node in graph
            await apply_gmail_label(db, request.userid, emails[0]['id'],"AI_Notify")
            return {
                "status": "completed",
                "category": "notify-human",
                "message": "Important/urgent email detected! Labeled as 'AI-Notify' in your Gmail for your review.",
                "subject": emails[0]['subject'],
                "sender": emails[0]['sender']
            }
        
        if category == "respond-act":
            # 1. Attempt to extract meeting details
            event_details = await extract_event_details_llm(emails[0]['body'], emails[0]['subject'])
            
            # 2. Check if a valid meeting request exists
            if event_details and event_details.get('slots'):
                # Attempt to book the slot based on your Vadodara schedule
                success, slot,event_id, reasons = await book_best_slot(db,request.userid, event_details)
                
                if success:
                    # 🟢 Path: Successful Booking
                    draft = await generate_meeting_response_llm(
                        original_subject=emails[0]['subject'],
                        original_body=emails[0]['body'],
                        event_details=event_details,
                        booked_slot=slot,
                        calendar_event_id=event_id
                    )
                else:

                    draft = await generate_meeting_response_llm(
                        original_subject=emails[0]['subject'],
                        original_body=emails[0]['body'],
                        event_details=event_details,
                        rejection_reasons=reasons or ["No available slots found"]
                    )
            else:
                # 🟡 Path: General Acknowledgement (No meeting found)
                print("Simple email - Using general acknowledgement strategy")
                draft = await generate_general_llm(
                    original_subject=emails[0]['subject'],
                    original_body=emails[0]['body']
                )

            # 3. Update the graph state so the draft is ready for the approve-action endpoint
            await app.state.agent.aupdate_state(config, {"final_reply": draft})

        response_data = {
            "thread_id": thread_id,
            "category": category,
            "sender": emails[0]['sender'],
            "subject": emails[0]['subject'],
            "proposed_reply": draft,
            "status": "waiting_for_approval" if category == "respond-act" else "completed"
        }
        return response_data
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
    
@app.post("/v1/approve-action")
async def approve_action(data: ApprovalActionRequest, db: AsyncConnection = Depends(get_db)):
    config = {"configurable": {"thread_id": data.thread_id}}
    
    try:
        # 1. Capture the decision (Approve, Deny, or Edit)
        state_update = {"hitl_decision": data.action}
        
        # CONDITION: EDIT - Update draft with user's manual changes
        if data.action == "edit" and data.edited_text:
            state_update["final_reply"] = data.edited_text
            
        await app.state.agent.aupdate_state(config, state_update)
        
        # 2. Resume the Graph to move past the checkpoint
        config["configurable"]["db"] = db
        await app.state.agent.ainvoke(None, config=config)
        
        # 3. Retrieve final state for execution
        final_state = await app.state.agent.aget_state(config)
        email_data = final_state.values.get("mail")
        reply_content = final_state.values.get("final_reply")

        # --- EXECUTION OF CONDITIONS ---
        original_subject = email_data.get('subject', 'No Subject')
        if not original_subject.lower().startswith("re:"):
            final_subject = f"Re: {original_subject}"
        else:
            final_subject = original_subject

        # CONDITION: APPROVE or EDIT - Send the email
        if data.action in ["approve", "edit"]:
            # Handle Calendar booking if details exist
            event_details = await extract_event_details_llm(email_data['body'], email_data['subject'])
            if event_details and event_details.get('slots'):
                await book_best_slot(db, data.user_id, event_details) #

            await send_reply(
                    db=db,
                    user_id=data.user_id,    # Changed from userid to user_id
                    to_email=email_data['sender'], # Changed from recipient to to_email
                    subject=final_subject,
                    message_text=reply_content # Changed from body to message_text
                )

        #CONDITION: ALL (Approve, Edit, and Deny) - Mark as read
        # This fulfills your requirement to mark received mail as read in every case
        await mark_as_processed(db, data.user_id, email_data['id']) #

        # Return specific messages based on the action taken
        messages = {
            "approve": "Email sent and marked as read.",
            "edit": "Edited email sent and marked as read.",
            "deny": "Email ignored and marked as read."
        }
        
        return {"status": "success", "message": messages.get(data.action, "Processed.")}

    except Exception as e:
        import traceback
        traceback.print_exc() #
        raise HTTPException(status_code=500, detail=str(e))