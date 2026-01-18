# import os
# from typing import Tuple
# from google.auth.transport.requests import Request
# from google.oauth2.credentials import Credentials
# from google_auth_oauthlib.flow import InstalledAppFlow
# from googleapiclient.discovery import build
# from dotenv import load_dotenv

# load_dotenv()

# SCOPES = [
#     'https://mail.google.com/',
#     'https://www.googleapis.com/auth/calendar'
# ]
# # CREDENTIALS_FILE = 'credentials/credentials.json'
# # TOKEN_FILE = 'credentials/token.json'

# BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# current_dir = os.path.dirname(os.path.abspath(__file__))

# # Move up 3 levels: tools -> src -> backend -> root
# # Then join with the 'credentials' folder and 'credentials.json' file
# project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
# CREDENTIALS_FILE = os.path.join(project_root, "credentials", "credentials.json")
# TOKEN_FILE = os.path.join(project_root, 'credentials', 'token.json')



# def get_services():
#     """Authenticates once and returns BOTH Gmail and Calendar services."""
#     creds = None
#     if os.path.exists(TOKEN_FILE):
#         creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
#     if not creds or not creds.valid:
#         if creds and creds.expired and creds.refresh_token:
#             creds.refresh(Request())
#         else:
#             flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
#             creds = flow.run_local_server(port=0)
        
#         with open(TOKEN_FILE, "w") as token:
#             token.write(creds.to_json())

#     gmail_service = build("gmail", "v1", credentials=creds)
#     calendar_service = build("calendar", "v3", credentials=creds)
    
#     return gmail_service, calendar_service


import os
import json
from typing import Dict, Any, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from psycopg import AsyncConnection

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
project_root = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))
CREDENTIALS_FILE = os.path.join(project_root, "credentials", "credentials.json")
TOKEN_FILE = os.path.join(project_root, 'credentials', 'token.json')

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

async def get_user_tokens(db: AsyncConnection, user_id: str) -> Optional[Dict[str, Any]]:
    async with db.cursor() as cur:
        await cur.execute("""
            SELECT access_token, refresh_token, token_uri, client_id, 
                   client_secret, scopes, expiry 
            FROM user_tokens WHERE user_id = %s
        """, (user_id,))
        row = await cur.fetchone()
        if row:
            return {
                'token': row[0],
                'refresh_token': row[1],
                'token_uri': row[2],
                'client_id': row[3],
                'client_secret': row[4],
                'scope': row[5],
                'expiry': row[6].isoformat() if row[6] else None
            }
        return None

async def get_user_service(db: AsyncConnection, user_id: str, service_name: str) -> Any:
    token_data = await get_user_tokens(db, user_id)
    if not token_data:
        raise ValueError(f"No tokens found for user {user_id}")
    
    # 1. PREPARE THE DATA
    # Create a copy so we don't accidentally mutate the original DB object
    info = dict(token_data)
    
    # Google's library specifically looks for the 'expiry' key.
    # We must strip the +05:30 offset because strptime in this library can't handle it.
    if "expiry" in info and isinstance(info["expiry"], str):
        # This takes "2026-01-11T12:00:00+05:30" -> "2026-01-11T12:00:00"
        clean_expiry = info["expiry"].split('+')[0].split('Z')[0]
        info["expiry"] = clean_expiry

    # 2. INITIALIZE (Only call this ONCE)
    try:
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    except ValueError as e:
        print(f"Failed to parse credentials: {e}")
        # Log the exact string that failed for debugging
        print(f"Problematic info: {info.get('expiry')}")
        raise

    # 3. REFRESH IF EXPIRED
    if creds.expired and creds.refresh_token:
        import asyncio
        from google.auth.transport.requests import Request as GoogleRequest
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, creds.refresh, GoogleRequest())
    
    version = 'v3' if service_name == 'calendar' else 'v1'
    return build(service_name, version, credentials=creds)