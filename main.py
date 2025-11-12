import streamlit as st
import requests
import pandas as pd
import os
from datetime import datetime
import plotly.express as px
from dotenv import load_dotenv
import json

# ---------------- Load Environment ----------------
load_dotenv()

# Render-compatible environment variables
PARENT_AGENT_URL = os.getenv("PARENT_AGENT_URL", "https://pos-parent-agent-v3.onrender.com/route")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")
NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Present Operating System (POS)",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- Header ----------------
col_header1, col_header2 = st.columns([8, 2])
with col_header1:
    st.title("🤖 Present Operating System (POS)")
    st.caption("All-in-one AI Task Management Dashboard — powered by Notion + Render Agents")
with col_header2:
    st.markdown(
        "<div style='text-align: right; font-size: 16px; font-weight: bold; color: #00FF7F;'>Made by Aayush Narwade</div>",
        unsafe_allow_html=True,
    )

# ---------------- Session State ----------------
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------------- Helper Functions ----------------
def call_parent_agent(message):
    """Send message to Parent Agent and return structured response."""
    try:
        resp = requests.post(PARENT_AGENT_URL, json={"message": message}, timeout=45)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def fetch_notion_tasks():
    """Fetch current tasks from Notion database."""
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        return pd.DataFrame()

    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    res = requests.post(url, headers=headers)
    if res.status_code != 200:
        return pd.DataFrame()

    data = res.json()
    tasks = []
    for item in data.get("results", []):
        props = item["properties"]
        tasks.append({
            "Task": props["Task"]["title"][0]["plain_text"] if props["Task"]["title"] else "",
            "PAEI Role": props["PAEI Role"]["select"]["name"] if props["PAEI Role"]["select"] else "",
            "XP": props["XP"]["number"],
            "Status": props["Status"]["select"]["name"] if props["Status"]["select"] else "",
            "Due Date": props["Due Date"]["date"]["start"] if props["Due Date"]["date"] else "",
            "Calendar Link": props["Calendar Link"]["url"],
            "Email Link": props["Email Link"]["url"]
        })
    return pd.DataFrame(tasks)

def get_paei_stats(df):
    """Calculate XP per PAEI Role."""
    if df.empty:
        return pd.DataFrame(columns=["PAEI Role", "XP"])
    
    stats = df.groupby("PAEI Role")["XP"].sum().reset_index()
    all_roles = ["Producer", "Administrator", "Entrepreneur", "Integrator"]
    stats = stats.set_index("PAEI Role").reindex(all_roles, fill_value=0).reset_index()
    return stats

# ---------------- Layout ----------------
col1, col2, col3 = st.columns([2.5, 5, 3.5])

# ---------------- Sidebar: To-Do Tasks ----------------
with col1:
    st.subheader("🧾 To-Do Tasks")
    tasks_df = fetch_notion_tasks()
    if not tasks_df.empty:
        todo_df = tasks_df[tasks_df["Status"] == "To Do"]
        for _, row in todo_df.iterrows():
            st.markdown(f"**{row['Task']}**")
            st.caption(f"🕒 {row['Due Date']} | 🎭 {row['PAEI Role']}")
            st.divider()
    else:
        st.info("No active tasks found or Notion credentials missing.")

# ---------------- Chatbot Interface ----------------
with col2:
    st.subheader("💬 Chat with POS")

    for msg in st.session_state.messages:
        role = "user" if msg["role"] == "user" else "assistant"
        with st.chat_message(role):
            st.markdown(msg["content"])

    user_input = st.chat_input("Type your message...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})

        response = call_parent_agent(user_input)
        agent_reply = ""

        if "intent" in response:
            intent = response["intent"]

            if intent == "TASK":
                agent_reply = "✅ Task allocated in Notion."

            elif intent == "CALENDAR":
                cal_resp = response.get("cal_resp", {})
                if isinstance(cal_resp, str):
                    try:
                        cal_resp = json.loads(cal_resp)
                    except Exception:
                        cal_resp = {"message": cal_resp}
                link = cal_resp.get("calendar_link") or cal_resp.get("html_link") or ""
                if link:
                    agent_reply = f"📅 Task scheduled successfully. [View in Calendar]({link})"
                else:
                    msg = cal_resp.get("message", "Calendar event created successfully.")
                    agent_reply = f"📅 {msg}"

            elif intent == "EMAIL":
                email_resp = response.get("email_resp", {})
                if isinstance(email_resp, str):
                    try:
                        email_resp = json.loads(email_resp)
                    except Exception:
                        email_resp = {"message": email_resp}
                brevo_data = email_resp.get("brevo_response", {})
                if isinstance(brevo_data, str):
                    try:
                        brevo_data = json.loads(brevo_data)
                    except Exception:
                        brevo_data = {"messageId": brevo_data}
                link = brevo_data.get("messageId", "")
                if link:
                    agent_reply = f"📨 Email sent successfully. Message ID: `{link}`"
                else:
                    msg = email_resp.get("message", "Email sent successfully.")
                    agent_reply = f"📨 {msg}"

            elif intent == "COMPLETION":
                xp_info = response.get("xp_resp", "")
                if isinstance(xp_info, (dict, list)) or len(str(xp_info)) > 120:
                    agent_reply = "🏆 Task completed. XP awarded!"
                else:
                    agent_reply = f"🏆 Task completed. XP awarded! {xp_info}"

            elif intent == "RESEARCH":
                research_resp = response.get("research_resp", {})
                research_data = research_resp.get("summary", {})

                if isinstance(research_data, str):
                    try:
                        research_data = json.loads(research_data)
                        if isinstance(research_data, str):
                            research_data = json.loads(research_data)
                    except Exception:
                        research_data = {"raw_text": research_data}

                exec_summary = research_data.get("executive_summary", [])
                key_findings = research_data.get("key_findings", [])
                sources = research_data.get("notable_sources", [])
                next_steps = research_data.get("recommended_next_steps", [])
                raw_text = research_data.get("raw_text", "")

                for field_name in ["exec_summary", "key_findings", "sources", "next_steps"]:
                    val = locals()[field_name]
                    if isinstance(val, str):
                        try:
                            locals()[field_name] = json.loads(val)
                        except Exception:
                            locals()[field_name] = [val]

                if exec_summary or key_findings or sources or next_steps:
                    agent_reply = "📚 **Research Summary:**\n\n"
                    if exec_summary:
                        agent_reply += "**Executive Summary:**\n" + "\n".join([f"- {x}" for x in exec_summary]) + "\n\n"
                    if key_findings:
                        agent_reply += "**Key Findings:**\n" + "\n".join([f"- {x}" for x in key_findings]) + "\n\n"
                    if sources:
                        agent_reply += "**Sources:**\n" + "\n".join([f"- {x}" for x in sources]) + "\n\n"
                    if next_steps:
                        agent_reply += "**Recommended Next Steps:**\n" + "\n".join([f"- {x}" for x in next_steps])
                elif raw_text:
                    agent_reply = f"📖 **Research Summary:**\n\n{raw_text}"
                else:
                    agent_reply = "📖 Research completed successfully, but no detailed summary was found."

            else:
                agent_reply = "🤖 Processed successfully."
        else:
            agent_reply = f"⚠️ Error: {response.get('error', 'Unknown issue')}"

        st.session_state.messages.append({"role": "assistant", "content": agent_reply})
        st.rerun()

# ---------------- PAEI Analysis Board ----------------
with col3:
    st.subheader("📊 PAEI Analysis Board")

    if not tasks_df.empty:
        paei_df = get_paei_stats(tasks_df)
        total_xp = paei_df["XP"].sum()
        st.metric(label="🏆 Total XP Gained", value=f"{total_xp} XP")

        fig = px.bar(
            paei_df,
            x="PAEI Role",
            y="XP",
            color="PAEI Role",
            title="XP Distribution by Role",
            text_auto=True,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No XP data available yet.")

# ---------------- Database Viewer ----------------
st.markdown("---")
st.subheader("📂 Notion Database Viewer")

if not tasks_df.empty:
    st.dataframe(tasks_df, use_container_width=True)
else:
    st.info("No data available to display.")

# ---------------- Render Deployment Hook ----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8501))
    st.write(f"✅ Streamlit running on Render port {port}")
