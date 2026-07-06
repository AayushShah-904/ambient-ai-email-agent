import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List

# Importing your existing production logic
from backend.src.tools.google_gmail import (fetch_emails, send_reply, mark_as_processed)

from backend.src.tools.google_calendar import (extract_event_details_llm, 
                                        book_best_slot, generate_reply_llm)

from contextlib import asynccontextmanager 
from psycopg_pool import AsyncConnectionPool
from psycopg import AsyncConnection
from googleapiclient.discovery import build 

import os
import requests
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from backend.src.tools.auth import get_user_service
from dotenv import load_dotenv
from backend.src.tools.auth import SCOPES, get_google_client_config
from backend.src.graph import create_graph
from backend.src.state import AgentState


load_dotenv()
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPES"] = "1"
# Configuration
DB_URI = os.getenv("DATABASE_URL")

# --- APP LIFESPAN ---
# In main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Run migrations/setup with dedicated conn string manager (autocommit-safe)
    async with AsyncPostgresSaver.from_conn_string(DB_URI) as setup_checkpointer:
        await setup_checkpointer.setup()

    # 2. Run the main pool for endpoint queries
    async with AsyncConnectionPool(conninfo=DB_URI, max_size=20) as pool:
        saver = AsyncPostgresSaver(pool)
        
        # 2. Compile the graph with the saver
        app.state.agent = create_graph(checkpointer=saver)
        
        print("Graph persistence initialized with PostgreSQL")
        yield {"db_pool": pool}

app = FastAPI(lifespan=lifespan)

# --- DEPENDENCY ---
async def get_db(request: Request):
    """Provides a database connection from the pool."""
    pool = request.state.db_pool
    async with pool.connection() as conn:
        yield conn


# --- AUTH ENDPOINTS ---
@app.get("/auth/login")
async def login():
    flow = Flow.from_client_config(get_google_client_config(), scopes=SCOPES)
    flow.redirect_uri = "http://localhost:8000/auth/callback"
    auth_url, _ = flow.authorization_url(access_type='offline', prompt='consent')
    return RedirectResponse(auth_url)

@app.get("/auth/callback")
async def callback(code: str, request: Request, db=Depends(get_db)):  # ✅ Fixed order
    flow = Flow.from_client_config(get_google_client_config(), scopes=SCOPES)
    flow.redirect_uri = "http://localhost:8000/auth/callback"
    flow.fetch_token(code=code)
    
    creds = flow.credentials
    session = requests.Session()
    user_info_response = session.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {creds.token}"}
    )
    if not user_info_response.ok:
        raise HTTPException(status_code=400, detail=f"Failed to fetch user info: {user_info_response.text}")
    
    user_info = user_info_response.json()
    full_email = user_info.get("email") 
    if not full_email:
        raise HTTPException(status_code=400, detail="Email address not returned by Google. Ensure scopes include email.")
        
    user_id = full_email.split('@')[0]

    print(f"✅ Saving tokens for user: {user_id}")
    
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
    
    return RedirectResponse(f"http://localhost:8501/?user_id={user_id}")

# --- SCHEMAS ---
class EmailDraftResponse(BaseModel):
    emailid: str      
    sender: str
    subject: str
    proposed_reply: str  
    status: str

class ApprovalRequest(BaseModel):
    userid: str
    emailid: str      
    sender: str
    subject: str
    replytext: str   
    approved: bool


class ScanRequest(BaseModel):
    userid: str

@app.post("/v1/scan-and-draft", response_model=EmailDraftResponse)
async def scan_and_draft(request: ScanRequest, db: AsyncConnection = Depends(get_db)):
    try:
        gmail_service = await get_user_service(db, request.userid, 'gmail')
        calendar_service = await get_user_service(db, request.userid, 'calendar')
        
        emails = await fetch_emails(db, request.userid,query='in:inbox')
        if not emails:
            raise HTTPException(status_code=404, detail="No unread emails found.")
        
        email = emails[0]
        event_details = extract_event_details_llm(email['body'], email['subject'])
        booked_success, slot, reasons = book_best_slot(calendar_service, event_details)
        
        # ✅ Variable assignment (consistent name)
        generated_text = generate_reply_llm(
            original_subject=email['subject'],
            original_body=email['body'],
            event_details=event_details,
            booked_slot=slot,
            rejection_reasons=reasons if not booked_success else None
        )

        if not emails:
            return {"status": "success", "message": "Inbox is clean! No new emails to process."}
        

        # ✅ Return matches your Pydantic schema exactly
        return {
            "emailid": email['id'],
            "sender": email['sender'],
            "subject": email['subject'],
            "proposed_reply": generated_text,
            "status": "pending_approval"
        }
    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/v1/discard-email")
async def discard_email(email_id: str, user_id: str, db: AsyncConnection = Depends(get_db)):
    # This ensures the email is removed from "Unread" so it won't be scanned again
    await mark_as_processed(db, user_id, email_id)
    return {"status": "success", "message": "Email archived and won't reappear."}

    
@app.post("/v1/approve-send")
async def approve_and_send(data: ApprovalRequest, db: AsyncConnection = Depends(get_db)):
    """
    Actual HITL confirmation endpoint.
    """
    if not data.approved:
        return {"message": "Action cancelled by user."}

    try:
        # 1. Final Send Action (Note  the 'await' and passing db/userid)
        success = await send_reply(
            db=db,
            user_id=data.userid,
            to_email=data.sender, 
            subject=data.subject, 
            message_text=data.replytext
        )
        
        if success:
            # 2. Mark as processed (Note the 'await')
            await mark_as_processed(db, data.userid, data.emailid)
            return {"status": "success", "message": "Email sent and marked as processed."}
        else:
            raise HTTPException(status_code=500, detail="Failed to send email reply.")
            
    except Exception as e:
        print(f"SEND ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error during sending: {str(e)}")

