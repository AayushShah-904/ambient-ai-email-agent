import os
from dotenv import load_dotenv
import streamlit as st
import requests
load_dotenv()

st.set_page_config(page_title="Email Assistant", layout="wide")

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
    """
    Sends the human's decision (approve/edit/deny) to the backend.
    This is how users control whether AI-drafted emails actually get sent.
    """
    try:
        payload = {
            "thread_id": thread_id,
            "action": action,
            "user_id": user_id,
            "edited_text": edited_text
        }
        response = requests.post(
            "http://localhost:8000/v1/approve-action", 
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
                            "http://localhost:8000/v1/scan-and-draft",
                        json={"userid": user_id},
                        timeout=150
                    )
                    if response.status_code == 200:
                        res_data = response.json()
                        if res_data.get("status") == "completed":
                            # Different UI feedback based on what the AI decided
                            category = res_data.get("category", "")
                            message = res_data.get("message", "Email processed")
                            
                            if category == "ignore":
                                st.success(f"**{message}**")
                                if res_data.get("subject"):
                                    st.caption(f"Subject: {res_data.get('subject')}")
                            
                            elif category == "notify-human":
                                st.warning(f"**{message}**")
                                if res_data.get("subject"):
                                    st.caption(f"Subject: {res_data.get('subject')}")
                                if res_data.get("sender"):
                                    st.caption(f"From: {res_data.get('sender')}")
                            
                            else:
                                st.info(message)
                            
                            if "draft_data" in st.session_state:
                                del st.session_state.draft_data
                        
                        elif res_data.get("status") == "empty":
                            st.info("No new emails found in your inbox!")
                        
                        else:
                            st.session_state.draft_data = res_data
                except requests.ConnectionError:
                    st.error("Cannot connect to backend. Is the FastAPI server running on port 8000?")
                except requests.Timeout:
                    st.error("Request timed out. The email processing took too long. Try again.")
                except requests.HTTPError as e:
                    st.error(f"Server error: {e.response.status_code}")
                except Exception as e:
                    st.error(f"Unexpected error: {str(e)}")
    
    # This column only shows up when there's a draft to review
    if "draft_data" in st.session_state:
        with col2:
            data = st.session_state.draft_data
            thread_id = data.get("thread_id")
            category = data.get("category", "unknown")
            
            st.markdown(f"**Category:** `{category.upper()}`")
            st.subheader(f"Draft for: **{data.get('sender', 'Unknown')}**")
            st.write(f"**Subject:** {data.get('subject', 'N/A')}")
            
            # User can edit the AI's draft before sending
            reply_text = st.text_area("Review/Edit AI Draft:", data.get('proposed_reply', ''), height=250)
            
            btn_col1, btn_col2, btn_col3 = st.columns(3)
            
            with btn_col1:
                if st.button("Approve", use_container_width=True):
                    res = handle_action(thread_id, "approve", user_id=user_id)
                    if res and res.status_code == 200:
                        response_data = res.json()
                        # We store the message before rerunning so it survives the page refresh
                        st.session_state.action_message = ("success", response_data.get("message", "Reply sent successfully!"))
                        del st.session_state.draft_data
                        st.rerun()

            with btn_col2:
                if st.button("Edit & Send", use_container_width=True):
                    res = handle_action(thread_id, "edit", user_id=user_id, edited_text=reply_text)
                    if res and res.status_code == 200:
                        response_data = res.json()
                        st.session_state.action_message = ("success", response_data.get("message", "Edited reply sent successfully!"))
                        del st.session_state.draft_data
                        st.rerun()

            with btn_col3:
                if st.button("Deny / Ignore", use_container_width=True):
                    res = handle_action(thread_id, "deny", user_id=user_id)
                    if res and res.status_code == 200:
                        response_data = res.json()
                        st.session_state.action_message = ("info", response_data.get("message", "Email marked as read (no reply sent)"))
                        del st.session_state.draft_data
                        st.rerun()

else:
    # User isn't logged in yet - show them the login button
    st.info("Click below to login")
    st.markdown("""
        <div style="text-align: center; padding: 2rem;">
            <a href="http://localhost:8000/auth/login" target="_self">
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