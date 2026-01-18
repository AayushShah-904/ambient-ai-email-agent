from pydantic import BaseModel

class EmailDraftResponse(BaseModel):
    email_id: str
    sender: str
    subject: str
    proposed_reply: str
    status: str

class ApprovalRequest(BaseModel):
    email_id: str
    sender: str
    subject: str
    reply_text: str
    approved: bool