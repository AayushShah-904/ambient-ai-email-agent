import streamlit as st
import requests

st.set_page_config(page_title="Email Assistant", layout="wide")

st.title("Email Assistant")


def get_user_id():
    """Checks for user ID in URL params (from OAuth callback) or session state"""
    user_id = st.query_params.get("user_id")
    if user_id:
        return user_id
    
    if "user_id" in st.session_state:
        return st.session_state.user_id
    
    return None

user_id = get_user_id()

if user_id:
    st.success(f"Logged in as: **{user_id}**")
    
    st.session_state.user_id = user_id
    
    col1, col2 = st.columns([1, 3])
    
    with col1:
        st.subheader("Quick Actions")
        if st.button("Scan for Emails", use_container_width=True):
            with st.spinner("Scanning inbox..."):
                try:
                    response = requests.post(
                        "http://localhost:8000/v1/scan-and-draft",
                        json={"userid": user_id},
                        timeout=30
                    )
                    if response.status_code == 200:
                        st.session_state.draft_data = response.json()
                        st.success("Draft ready!")
                    else:
                        st.error(f"API Error: {response.status_code}")
                except Exception as e:
                    st.error(f"Connection failed: {str(e)}")
    
    with col2:
        if "draft_data" in st.session_state:
            data = st.session_state.draft_data
            st.subheader(f"Draft from: **{data.get('sender', 'Unknown')}**")
            st.write(f"**Subject:** {data.get('subject', 'N/A')}")
            
            # User can edit the AI-generated draft before sending
            reply_text = st.text_area("Reply Preview:", data.get('proposed_reply', ''), height=200)
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("Send Reply", use_container_width=True):
                    with st.spinner("Sending email..."):
                        try:
                            payload = {
                                "userid": user_id,
                                "emailid": data.get("emailid"),
                                "sender": data.get("sender"),
                                "subject": data.get("subject"),
                                "replytext": reply_text,
                                "approved": True
                            }
                            
                            response = requests.post(
                                "http://localhost:8000/v1/approve-send",
                                json=payload,
                                timeout=30
                            )
                            
                            if response.status_code == 200:
                                st.success("Email dispatched successfully!")
                                del st.session_state.draft_data
                            else:
                                error_detail = response.json().get('detail', 'Unknown error')
                                st.error(f"Failed to send: {error_detail}")
                        except Exception as e:
                            st.error(f"Connection error: {str(e)}")
            
            with col_btn2:
                if st.button("Discard Draft", use_container_width=True):
                    del st.session_state.draft_data
                    st.rerun()

else:
    # User needs to log in first
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
    
    st.info("**After login:** Return here and refresh page (F5)")

