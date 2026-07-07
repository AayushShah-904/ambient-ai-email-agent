import os
from dotenv import load_dotenv
import streamlit as st
import requests

# This must be the very first Streamlit command executed!
st.set_page_config(page_title="Email Assistant", layout="wide")

load_dotenv()

import pathlib

# Support both local .env and Streamlit Community Cloud secrets
def _get_secret(key: str, default: str) -> str:
    """Read from env vars (local) first, then Streamlit secrets (cloud)."""
    val = os.getenv(key)
    if val is not None:
        return val
        
    # Only fall back to st.secrets if running on Streamlit Cloud or if the secrets file exists on disk
    is_cloud = os.getenv("STREAMLIT_SHARING_MODE") is not None
    local_secrets = pathlib.Path(".streamlit/secrets.toml")
    global_secrets = pathlib.Path.home() / ".streamlit" / "secrets.toml"
    
    if is_cloud or local_secrets.exists() or global_secrets.exists():
        try:
            return st.secrets[key]
        except Exception:
            pass
    return default

BACKEND_URL = _get_secret("BACKEND_URL", "http://localhost:8000")
# Browser-facing URL for OAuth login redirects (must be accessible from the user's browser)
PUBLIC_BACKEND_URL = _get_secret("PUBLIC_BACKEND_URL", "http://localhost:8000")

st.title("Email Assistant")

def get_user_id():
    """Check if user is logged in by looking for their ID in URL params or session"""
    user_id = st.query_params.get("user_id")
    if user_id:
        return user_id
    if "user_id" in st.session_state:
        return st.session_state.user_id
    return None

user_id = get_user_id()

def handle_action(thread_id, action, user_id, edited_text=None):
    """Sends the human's decision (approve/edit/deny) to the backend."""
    try:
        payload = {
            "thread_id": thread_id,
            "action": action,
            "user_id": user_id,
            "edited_text": edited_text
        }
        response = requests.post(
            f"{BACKEND_URL}/v1/approve-action", 
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        return response
    except requests.ConnectionError:
        st.error("Cannot connect to backend server")
        return None
    except requests.Timeout:
        st.error("Request timed out")
        return None
    except requests.HTTPError as e:
        st.error(f"Server error: {e.response.status_code}")
        return None
    except Exception as e:
        st.error(f"Action failed: {str(e)}")
        return None

if user_id:
    st.success(f"Logged in as: **{user_id}**")
    st.session_state.user_id = user_id
    
    # Show any success/error messages from the previous action
    if "action_message" in st.session_state:
        msg_type, msg_text = st.session_state.action_message
        if msg_type == "success":
            st.success(msg_text)
        elif msg_type == "info":
            st.info(msg_text)
        elif msg_type == "warning":
            st.warning(msg_text)
        del st.session_state.action_message
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        st.subheader("Quick Actions")
        if st.button("Scan for Emails", use_container_width=True):
            with st.spinner("Scanning inbox..."):
                try:    
                    response = requests.post(
                        f"{BACKEND_URL}/v1/scan-and-draft",
                        json={"userid": user_id},
                        timeout=150
                    )
                    if response.status_code == 200:
                        res_data = response.json()
                        
                        if res_data.get("status") == "empty":
                            st.info("No new emails found in your inbox!")
                        
                        elif res_data.get("status") == "success":
                            results = res_data.get("results", [])
                            
                            drafts_needing_approval = []
                            auto_processed = []
                            
                            for result in results:
                                if result.get("status") == "waiting_for_approval":
                                    drafts_needing_approval.append(result)
                                else:
                                    auto_processed.append(result)
                            
                            for item in auto_processed:
                                category = item.get("category", "")
                                subject = item.get("subject", "No subject")
                                if category == "ignore":
                                    st.success(f"**Email auto-archived:** {subject}")
                                elif category == "notify-human":
                                    st.warning(f"**Email flagged for your attention:** {subject}")
                            
                            if drafts_needing_approval:
                                st.session_state.draft_data = drafts_needing_approval
                                st.session_state.current_draft_index = 0
                            elif "draft_data" in st.session_state:
                                del st.session_state.draft_data
                        
                        elif res_data.get("status") == "completed":
                            st.info(res_data.get("message", "Email processed"))
                            if "draft_data" in st.session_state:
                                del st.session_state.draft_data
                        
                except Exception as e:
                    st.error(f"Unexpected error: {str(e)}")
    
    # Review Logic Column
    if "draft_data" in st.session_state:
        with col2:
            drafts = st.session_state.draft_data
            current_index = st.session_state.get("current_draft_index", 0)
            
            # Safe boundary check
            if current_index >= len(drafts):
                current_index = 0
                st.session_state.current_draft_index = 0
            
            if len(drafts) > 1:
                st.info(f"📧 **Email {current_index + 1} of {len(drafts)}** - Review and approve each email")
            
            # 🟢 Retrieve data for the specific current email
            data = drafts[current_index]
            thread_id = data.get("thread_id")
            category = data.get("category", "unknown")
            subject = data.get("subject", "N/A")
            
            st.markdown(f"**Category:** `{category.upper()}`")
            st.subheader(f"Draft for: **{data.get('sender', 'Unknown')}**")
            st.write(f"**Subject:** {subject}")
            
            # 🟢 Use thread_id as the key to prevent widget state flickering
            reply_text = st.text_area(
                "Review/Edit AI Draft:", 
                data.get('proposed_reply_plain', 'No draft generated.'), 
                height=250, 
                key=f"draft_text_{thread_id}"
            )
            
            btn_col1, btn_col2, btn_col3 = st.columns(3)
            
            with btn_col1:
                if st.button("✅ Approve", use_container_width=True, key=f"approve_{thread_id}"):
                    res = handle_action(thread_id, "approve", user_id=user_id)
                    if res and res.status_code == 200:
                        st.session_state.action_message = ("success", "Reply sent successfully!")
                        drafts.pop(current_index)
                        # 🟢 Recalculate robust index
                        if not drafts:
                            st.session_state.pop("draft_data", None)
                            st.session_state.pop("current_draft_index", None)
                        else:
                            st.session_state.current_draft_index = max(0, min(current_index, len(drafts) - 1))
                        st.rerun()

            with btn_col2:
                if st.button("✏️ Edit & Send", use_container_width=True, key=f"edit_{thread_id}"):
                    res = handle_action(thread_id, "edit", user_id=user_id, edited_text=reply_text)
                    if res and res.status_code == 200:
                        st.session_state.action_message = ("success", "Edited reply sent successfully!")
                        drafts.pop(current_index)
                        if not drafts:
                            st.session_state.pop("draft_data", None)
                            st.session_state.pop("current_draft_index", None)
                        else:
                            st.session_state.current_draft_index = max(0, min(current_index, len(drafts) - 1))
                        st.rerun()

            with btn_col3:
                # 🟢 Clean Deny Logic: Triggers calendar deletion in backend
                if st.button("❌ Deny / Ignore", use_container_width=True, key=f"deny_{thread_id}"):
                    res = handle_action(thread_id, "deny", user_id=user_id)
                    if res and res.status_code == 200:
                        response_data = res.json()
                        st.session_state.action_message = ("info", response_data.get("message", "Email marked as read"))
                        st.toast(f"Event for '{subject}' was removed from calendar.", icon="🗑️")
                        
                        drafts.pop(current_index)
                        if not drafts:
                            st.session_state.pop("draft_data", None)
                            st.session_state.pop("current_draft_index", None)
                        else:
                            # 🟢 Adjust index to prevent overflow
                            st.session_state.current_draft_index = max(0, min(current_index, len(drafts) - 1))
                        st.rerun()
            
            # Navigation controls
            if len(drafts) > 1:
                st.divider()
                nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
                with nav_col1:
                    if current_index > 0:
                        if st.button("⬅️ Previous", use_container_width=True):
                            st.session_state.current_draft_index = current_index - 1
                            st.rerun()
                with nav_col2:
                    st.markdown(f"<div style='text-align: center; padding: 10px;'>Reviewing Draft {current_index + 1} of {len(drafts)}</div>", unsafe_allow_html=True)
                with nav_col3:
                    if current_index < len(drafts) - 1:
                        if st.button("Next ➡️", use_container_width=True):
                            st.session_state.current_draft_index = current_index + 1
                            st.rerun()

else:
    st.info("Click below to login")
    login_url = f"{PUBLIC_BACKEND_URL}/auth/login"
    st.markdown(f"""
        <div style="text-align: center; padding: 2rem;">
            <a href="{login_url}" target="_self">
                <button style="
                    width: 100%; height: 60px; font-size: 20px; 
                    background: #4285f4; color: white; border: none; 
                    border-radius: 12px; cursor: pointer; box-shadow: 0 4px 8px rgba(0,0,0,0.2);
                ">
                    Login with Google
                </button>
            </a>
        </div>
    """, unsafe_allow_html=True)