import streamlit as st
from notion_client import Client
from datetime import date
import os
from dotenv import load_dotenv
import pandas as pd
import requests
import google.generativeai as genai
import html

# ================== ENV ==================
load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
PARENT_AGENT_URL = os.getenv("PARENT_AGENT_URL", "http://localhost:8080/route")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ================== INIT ==================
notion = Client(auth=NOTION_API_KEY)

use_research = bool(GEMINI_API_KEY)
if use_research:
    genai.configure(api_key=GEMINI_API_KEY)
    research_model = genai.GenerativeModel("gemini-1.5-flash")   # ✅ stable model

# ================== UI SETUP ==================
st.set_page_config(page_title="POS-MVP", page_icon="⚡", layout="wide")
st.title("⚡ Present Operating System - MVP")
st.markdown("Talk to your POS agent — tasks are auto-created in Notion, questions return concise research answers.")

# ================== STYLES ==================
st.markdown("""
<style>
.bubble {padding: 12px 14px; margin: 8px 0; border-radius: 14px; line-height: 1.45; font-size: 0.98rem;}
.user {background: #1f6feb20; border: 1px solid #1f6feb55; color: #e6edf3;}
.ai {background: #161b22; border: 1px solid #30363d; color: #c9d1d9;}
</style>
""", unsafe_allow_html=True)

def bubble(text, who="user"):
    text = html.escape(text).replace("\n", "<br>")
    st.markdown(f'<div class="bubble {who}">{text}</div>', unsafe_allow_html=True)

# ================== GET TASKS FROM NOTION ==================
st.subheader("📋 Current Notion Tasks")

def safe_get(props, key, path):
    try:
        val = props.get(key)
        if not val:
            return "-"
        for p in path:
            if isinstance(p, int):
                val = val[p] if isinstance(val, list) and len(val) > p else "-"
            else:
                val = val.get(p) if isinstance(val, dict) else "-"
        return val if val else "-"
    except:
        return "-"

def load_tasks():
    result = notion.databases.query(database_id=DATABASE_ID)  # ✅ fixed
    rows = result.get("results", [])
    tasks = [{
        "Task Name": safe_get(p["properties"], "Name", ["title", 0, "plain_text"]),
        "Status": safe_get(p["properties"], "Status", ["select", "name"]),
        "Avatar": safe_get(p["properties"], "Avatar", ["select", "name"]),
        "XP": safe_get(p["properties"], "XP", ["number"]),
        "Due Date": safe_get(p["properties"], "Due Date", ["date", "start"])
    } for p in rows]
    st.dataframe(pd.DataFrame(tasks), use_container_width=True)

try:
    load_tasks()
except Exception as e:
    st.error(f"⚠️ Error fetching tasks: {e}")

# ================== CHAT SECTION ==================
st.subheader("💬 Talk to POS Agent")

if "chat" not in st.session_state:
    st.session_state.chat = []

nl_input = st.text_input("Ask a question or say a task like 'remind me to call Priya at 6pm'")

def add_to_notion(task):
    try:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                "Name": {"title": [{"text": {"content": task}}]},
                "Status": {"select": {"name": "To Do"}},
                "Avatar": {"select": {"name": "Producer"}},
                "XP": {"number": 0}
            },
        )
        return True, None
    except Exception as e:
        return False, str(e)

def research_answer(question):
    try:
        ans = research_model.generate_content(
            f"Answer this in 1-2 concise sentences:\n\n{question}",
            generation_config={"max_output_tokens": 256},
        )
        if not ans.text:
            return "I couldn't find the answer."
        return ans.text.strip()
    except Exception as e:
        return f"(research error) {e}"

# render chat history
for msg in st.session_state.chat:
    bubble(msg["text"], "user" if msg["role"] == "user" else "ai")

col1, col2 = st.columns([1,1])
send = col1.button("Send to POS")
clear = col2.button("Clear chat")

if clear:
    st.session_state.chat = []
    st.experimental_rerun()

if send and nl_input.strip():
    bubble(nl_input, "user")
    st.session_state.chat.append({"role": "user", "text": nl_input})

    try:
        r = requests.post(PARENT_AGENT_URL, json={"message": nl_input}, timeout=20)
        routed = r.json()
        intent = routed.get("intent", "UNKNOWN")
        data = routed.get("data", nl_input)

        if intent == "TASK":
            ok, err = add_to_notion(data)
            if ok:
                reply = f"✅ Task added to Notion: “{data}”"
                bubble(reply, "ai")
                st.session_state.chat.append({"role": "assistant", "text": reply})

                # 🔄 REFRESH UI INSTANTLY
                st.experimental_rerun()
            else:
                reply = f"❌ Failed: {err}"
                bubble(reply, "ai")
                st.session_state.chat.append({"role": "assistant", "text": reply})

        elif intent == "RESEARCH":
            if not use_research:
                reply = "⚠️ Research disabled (no GEMINI_API_KEY set)."
            else:
                reply = research_answer(data)
            bubble(reply, "ai")
            st.session_state.chat.append({"role": "assistant", "text": reply})

        else:
            reply = "I couldn't classify that. Try a task or a question."
            bubble(reply, "ai")
            st.session_state.chat.append({"role": "assistant", "text": reply})

    except Exception as e:
        reply = f"❌ Could not reach Parent Agent server.\n\n{e}"
        bubble(reply, "ai")
        st.session_state.chat.append({"role": "assistant", "text": reply})
