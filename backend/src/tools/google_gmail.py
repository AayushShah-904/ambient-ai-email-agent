import os
import sys
import asyncio
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import base64
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Optional, Tuple
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource
from googleapiclient.discovery import build
from psycopg import AsyncConnection
from dotenv import load_dotenv

from backend.src.tools.auth import get_user_service 

load_dotenv()

SCOPES = ['https://mail.google.com/', 'https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'credentials/credentials.json'
TOKEN_FILE = 'credentials/token.json'

async def get_gmail_service(db: AsyncConnection, user_id: str) -> Resource:
    """Gets authenticated Gmail service for a specific user"""
    return await get_user_service(db, user_id, 'gmail')
    
def get_clean_body(payload: dict) -> Optional[str]:
    """
    Gmail messages come in a complex nested format. This extracts just the readable text.
    We look for 'text/plain' parts and decode them from base64.
    """
    if 'parts' not in payload:
        if payload.get('mimeType') == 'text/plain':
            data = payload['body'].get('data')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8')
    else:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8')
    return None

def get_sender_display_name(full_msg: dict) -> str:
    """
    Extracts first name (e.g. 'Alice') from Gmail message's From header.
    Falls back to 'Guest' if no name is present.
    """
    if 'payload' not in full_msg:
        return "Guest"
    
    headers = full_msg['payload']['headers']
    sender_header = next((h['value'] for h in headers if h['name'] == 'From'), None)
    
    if not sender_header:
        return "Guest"
    
    name, _ = parseaddr(sender_header)
    if not name:
        return "Guest"
    
    # Use first token as first name
    return name.split()[0]


def get_sender_and_subject(full_msg: dict) -> Tuple[Optional[str], Optional[str]]:
    """Digs through Gmail's headers to find who sent it and what the subject line is"""
    headers = full_msg['payload']['headers']
    sender = next((h['value'] for h in headers if h['name'] == 'From'), None)
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
    return sender, subject

async def send_reply(db: AsyncConnection, user_id: str, to_email: str, subject: str, message_text: str) -> bool:
    """
    Sends an email reply via Gmail API using run_in_executor to avoid blocking.
    Returns True if it worked, False if something went wrong.
    """
    
    service = await get_gmail_service(db, user_id)
    try:
        loop = asyncio.get_running_loop()
        message = MIMEText(message_text,'html')
        message['to'] = to_email
        message['subject'] = subject
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        body = {'raw': raw_message}
        
        sent_message = await loop.run_in_executor(
            None,
            lambda: service.users().messages().send(userId='me', body=body).execute()
        )
        print(f'Reply sent to {to_email} ID: {sent_message["id"]}')
        return True
    except Exception as e:
        print(f'Could not send reply: {e}')
        return False

async def mark_as_processed(db: AsyncConnection, user_id: str, msg_id: str) -> bool:
    """Marks an email as read by removing the UNREAD label using run_in_executor."""
    
    service = await get_gmail_service(db, user_id)
    try:
        loop = asyncio.get_running_loop()
        body = {'removeLabelIds': ['UNREAD']}
        await loop.run_in_executor(
            None,
            lambda: service.users().messages().modify(userId='me', id=msg_id, body=body).execute()
        )
        print(f'Email {msg_id} marked as PROCESSED.')
        return True
    except Exception as e:
        print(f'Could not modify label: {e}')
        return False

async def apply_gmail_label(db: AsyncConnection, user_id: str, msg_id: str, label_name: str = "AI-Notify") -> bool:
    """
    Adds a custom label to an email (like a folder or tag) using run_in_executor.
    If the label doesn't exist yet, we create it first.
    This is how we mark important emails for human review.
    """
    
    service = await get_gmail_service(db, user_id)
    try:
        loop = asyncio.get_running_loop()
        
        # Check if the label already exists
        results = await loop.run_in_executor(
            None,
            lambda: service.users().labels().list(userId='me').execute()
        )
        labels = results.get('labels', [])
        label_id = next((l['id'] for l in labels if l['name'] == label_name), None)

        # Create it if it doesn't exist
        if not label_id:
            label_body = {
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show"
            }
            created_label = await loop.run_in_executor(
                None,
                lambda: service.users().labels().create(userId='me', body=label_body).execute()
            )
            label_id = created_label['id']
            print(f"Created new Gmail label: {label_name}")

        # Apply the label to the email
        body = {'addLabelIds': [label_id]} 
        await loop.run_in_executor(
            None,
            lambda: service.users().messages().modify(userId='me', id=msg_id, body=body).execute()
        )
        print(f"Applied {label_name} to message {msg_id}")
        return True
    except Exception as e:
        print(f"Label Error: {e}")
        return False
    

async def fetch_emails(db: AsyncConnection, user_id: str, query: str = 'in:inbox is:unread -category:social -category:promotions') -> list:
    """
    Gets unread emails from the PRIMARY inbox only.
    We skip social media, promotions, and forum emails - just the important stuff.
    #-category:updates -category:forums
    """
    
    service = await get_gmail_service(db, user_id)
    
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(
        None,
        lambda: service.users().messages().list(
            userId='me', 
            q=query,  
            maxResults=10
        ).execute()
    )
    
    messages = results.get('messages', [])
    emails = []
    
    for msg in messages:
        # Fetch full message details for each email
        full_msg = await loop.run_in_executor(
            None,
            lambda: service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        )
        
        sender, subject = get_sender_and_subject(full_msg)
        body = get_clean_body(full_msg['payload']) or "No plain text"
        # Truncate long emails to keep things manageable
        emails.append({
            'id': msg['id'], 
            'subject': subject, 
            'sender': sender, 
            'body': body[:500] + '...' if len(body) > 500 else body
        })
    return emails
