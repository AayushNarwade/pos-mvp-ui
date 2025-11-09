import os
import html
import requests
import pandas as pd
import streamlit as st
from datetime import date
from dotenv import load_dotenv
from notion_client import Client
import google.generativeai as genai

# ------------------ ENV ------------------
load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
PARENT_AGENT_URL = os.getenv("PARENT_AGENT_URL", "http://localhost:8080/route")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ------------------ CLIENTS ------------------
notion = Client(auth=NOTION_API_KEY)

use_research = bool(GEMINI_API_KEY)
if use_research:
    genai.configure(api_key=GEMINI_API_KEY)
    research_model = genai.GenerativeModel("gemini-2.0-flash")  # concise, fast

# ------------------ UI SETUP ------------------
st.set_page_config(page_title="POS-MVP", page_icon="⚡", layout="wide")
st.title("⚡ Present Operating System - MVP")
st.markdown("Talk to your POS agent — tasks are auto-created in Notion; questions return concise research answers.")

st.markdown("""
<style>
.bubble {padding:12px 14px;margin:8px 0;border-radius:14px;line-height:1.45;font-size:0.98rem;}
.user {background:#1f6feb20;border:1px solid #1f6feb55;color:#e6edf3;}
.ai   {background:#161b22;border:1px solid #30363d;color:#c9d1d9;}
</style>
""", unsafe_allow_html=True)

def bubble(text, who="user"):
    text = html.escape(text).replace("\n", "<br>")
    st.markdown(f'<div class="bubble {who}">{text}</div>', unsafe_allow_html=True)

# ------------------ NOTION HELPERS ------------------
def safe_get(props, key, path):
    try:
        val = props.get(key)
        if not val: return "-"
        for p in path:
            if isinstance(p, int):
                val = val[p] if isinstance(val, list) and len(val) > p else "-"
            else:
                val = val.get(p) if isinstance(val, dict) else "-"
        return val if val else "-"
    except Exception:
        return "-"

def fetch_tasks_df():
    res = notion.databases.query(database_id=DATABASE_ID)
    rows = res.get("results", [])
    tasks = [{
        "Task Name": safe_get(p["properties"], "Name", ["title", 0, "plain_text"]),
        "Status":    safe_get(p["properties"], "Status", ["select", "name"]),
        "Avatar":    safe_get(p["properties"], "Avatar", ["select", "name"]),
        "XP":        safe_get(p["properties"], "XP", ["number"]),
        "Due Date":  safe_get(p["properties"], "Due Date", ["date", "start"]),
    } for p in rows]
    return pd.DataFrame(tasks)

def add_task_to_notion_clean(title: str, due_iso: str | None):
    props = {
        "Name":   {"title": [{"text": {"content": title}}]},
        "Status": {"select": {"name": "To Do"}},
        "Avatar": {"select": {"name": "Producer"}},
        "XP":     {"number": 0},
    }
    if due_iso:
        props["Due Date"] = {"date": {"start": due_iso}}  # already ISO with +05:30
    notion.pages.create(parent={"database_id": DATABASE_ID}, properties=props)

# ------------------ SECTION: TASKS TABLE ------------------
st.subheader("📋 Current Notion Tasks")
tasks_df = fetch_tasks_df()
st.dataframe(tasks_df, use_container_width=True)

# ------------------ SECTION: CHAT ------------------
st.subheader("💬 Talk to POS Agent")
if "chat" not in st.session_state:
    st.session_state.chat = []

nl_input = st.text_input("Ask a question or say a task like 'remind me to call Priya at 6pm'")

def research_answer(q: str) -> str:
    try:
        ans = research_model.generate_content(
            f"Answer in 1–2 concise sentences:\n\n{q}",
            generation_config={"max_output_tokens": 256},
        )
        return (ans.text or "I couldn't find the answer.").strip()
    except Exception as e:
        return f"(research error) {e}"

# Render chat history
for msg in st.session_state.chat:
    bubble(msg["text"], "user" if msg["role"] == "user" else "ai")

col1, col2 = st.columns([1,1])
send = col1.button("Send to POS")
clear = col2.button("Clear chat")

if clear:
    st.session_state.chat = []
    st.rerun()

if send and nl_input.strip():
    # show user bubble
    st.session_state.chat.append({"role": "user", "text": nl_input})
    bubble(nl_input, "user")

    try:
        r = requests.post(PARENT_AGENT_URL, json={"message": nl_input}, timeout=20)
        routed = r.json()
        intent = routed.get("intent", "UNKNOWN")
        data   = routed.get("data", nl_input)

        if intent == "TASK":
            task = routed.get("task") or {}
            title = task.get("title") or data
            due_iso = task.get("datetime_iso")  # may be None

            try:
                add_task_to_notion_clean(title, due_iso)
                reply = f"✅ Task added to Notion: “{title}”" + (f" — due {due_iso}" if due_iso else "")
                st.session_state.chat.append({"role": "assistant", "text": reply})
                bubble(reply, "ai")
                # refresh table immediately
                st.rerun()
            except Exception as e:
                msg = f"❌ Failed to add task: {e}"
                st.session_state.chat.append({"role": "assistant", "text": msg})
                bubble(msg, "ai")

        elif intent == "RESEARCH":
            if not use_research:
                reply = "⚠️ Research disabled (no GEMINI_API_KEY set)."
            else:
                reply = research_answer(data)
            st.session_state.chat.append({"role": "assistant", "text": reply})
            bubble(reply, "ai")

        else:
            reply = "I couldn't classify that. Try a task or a question."
            st.session_state.chat.append({"role": "assistant", "text": reply})
            bubble(reply, "ai")

    except Exception as e:
        reply = f"❌ Could not reach Parent Agent server.\n\n{e}"
        st.session_state.chat.append({"role": "assistant", "text": reply})
        bubble(reply, "ai")
