import streamlit as st
from notion_client import Client
from datetime import date, datetime
import os
from dotenv import load_dotenv
import pandas as pd
import requests
import google.generativeai as genai
import html
import re
import time

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
    research_model = genai.GenerativeModel("gemini-2.5-flash")


# ================== UI SETUP ==================
st.set_page_config(page_title="POS-MVP", page_icon="⚡", layout="wide")
st.title("⚡ Present Operating System - MVP")
st.markdown("Talk to your POS agent — tasks are auto-created in Notion, questions return research answers.")


# ========== Custom CSS for premium bubbles ==========
st.markdown("""
<style>
.chat-container { max-width: 900px; margin: 0 auto; }
.bubble { padding: 12px 14px; margin: 8px 0; border-radius: 14px; line-height: 1.45; font-size: 0.98rem; }
.user { background: #1f6feb20; border: 1px solid #1f6feb55; color: #e6edf3; align-self: flex-end; }
.ai   { background: #161b22; border: 1px solid #30363d; color: #c9d1d9; }
.meta { font-size: 0.8rem; color: #8b949e; margin-top: -4px; margin-bottom: 6px;}
.row { display: flex; flex-direction: column; }
.loader { color: #8b949e; font-style: italic; padding: 6px 2px; }
</style>
<div class="chat-container"></div>
""", unsafe_allow_html=True)


# ================== Helpers ==================
def render_bubble(text: str, who: str = "user"):
    text = html.escape(text).replace("\n", "<br>")
    cls = "user" if who == "user" else "ai"
    st.markdown(f"""<div class="row"><div class="bubble {cls}">{text}</div></div>""",
                unsafe_allow_html=True)


def detect_status(text: str) -> str:
    """Smart status assignment based on time / completion language."""
    lowered = text.lower()
    # Finished / done case
    if any(x in lowered for x in ["finished", "done", "completed", "sent already"]):
        return "Done"
    # Today case
    today = datetime.now().strftime("%Y-%m-%d")
    if "today" in lowered or today in lowered or "tonight" in lowered:
        return "In Progress"
    # Default
    return "To Do"


def detect_avatar(text: str) -> str:
    lowered = text.lower()
    mapping = {
        "Producer": ["create", "build", "write", "record", "design", "develop", "make"],
        "Entrepreneur": ["pitch", "sell", "client", "sponsor", "investor", "market"],
        "Administrator": ["email", "schedule", "organize", "submit", "send", "update"],
        "Integrator": ["plan", "align", "sync", "review", "strategy", "roadmap"]
    }
    for avatar, words in mapping.items():
        if any(w in lowered for w in words):
            return avatar
    return "Producer"  # fallback


def extract_due_date(text: str) -> str | None:
    """Very basic due date extraction (MVP). Supports 'today', 'tomorrow', or YYYY-MM-DD."""
    lowered = text.lower()
    if "today" in lowered:
        return date.today().isoformat()
    if "tomorrow" in lowered:
        return (date.today()).replace(day=date.today().day + 1).isoformat()
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    return m.group(1) if m else None


def add_task_to_notion(text: str):
    """Use all auto-detected fields to create task."""
    status = detect_status(text)
    avatar = detect_avatar(text)
    due = extract_due_date(text)

    try:
        props = {
            "Name": {"title": [{"text": {"content": text}}]},
            "Status": {"select": {"name": status}},
            "Avatar": {"select": {"name": avatar}},
            "XP": {"number": 0},
        }
        if due:
            props["Due Date"] = {"date": {"start": due}}

        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties=props,
        )
        return True, None
    except Exception as e:
        return False, str(e)


def research_answer(question: str) -> str:
    """1–2 sentence factual response."""
    prompt = (
        "Answer the following question in 1–2 factual sentences, no bullet points, no markdown:\n\n"
        f"Question: {question}"
    )
    try:
        resp = research_model.generate_content(prompt, generation_config={"max_output_tokens": 256})
        return (resp.text or "").strip()
    except Exception as e:
        return f"(research error) {e}"


# ================== Load Notion Tasks ==================
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
    except Exception:
        return "-"

try:
    response = notion.databases.query(database_id=DATABASE_ID)
    results = response.get("results", [])
    if results:
        tasks = []
        for page in results:
            props = page["properties"]
            tasks.append({
                "Task Name": safe_get(props, "Name", ["title", 0, "plain_text"]),
                "Status": safe_get(props, "Status", ["select", "name"]),
                "Avatar": safe_get(props, "Avatar", ["select", "name"]),
                "XP": safe_get(props, "XP", ["number"]),
                "Due Date": safe_get(props, "Due Date", ["date", "start"]),
            })
        st.dataframe(pd.DataFrame(tasks), use_container_width=True)
    else:
        st.info("No tasks found in your Notion database.")
except Exception as e:
    st.error(f"⚠️ Error fetching tasks: {e}")


# ================== PHASE 2 — Chat with POS ==================
st.subheader("💬 Talk to POS Agent")

if "chat" not in st.session_state:
    st.session_state.chat = []

nl_input = st.text_input("Type something like: `remind me to email Sarah at 5pm`")

# Render chat history
for msg in st.session_state.chat:
    render_bubble(msg["text"], "user" if msg["role"] == "user" else "assistant")

colA, colB = st.columns([1, 1])
with colA:
    send = st.button("Send to POS")
with colB:
    clear = st.button("Clear chat")

if clear:
    st.session_state.chat = []
    st.rerun()

if send:
    if not nl_input.strip():
        st.warning("Please type something.")
    else:
        st.session_state.chat.append({"role": "user", "text": nl_input})
        render_bubble(nl_input, "user")

        # LOADING placeholder
        with st.spinner("🧠 POS is thinking..."):
            try:
                r = requests.post(PARENT_AGENT_URL, json={"message": nl_input}, timeout=20)
                routed = r.json()
                intent = routed.get("intent", "UNKNOWN")
                data = routed.get("data", nl_input)

                if intent == "TASK":
                    ok, err = add_task_to_notion(data)
                    reply = f"✅ Added task to Notion: “{data}”" if ok else f"❌ Failed to add task: {err}"
                    st.session_state.chat.append({"role": "assistant", "text": reply})
                    st.rerun()

                elif intent == "RESEARCH":
                    if not use_research:
                        reply = "❌ Research mode disabled (missing GEMINI_API_KEY)."
                    else:
                        answer = research_answer(data)
                        reply = answer or "I couldn't find a clear answer."
                    st.session_state.chat.append({"role": "assistant", "text": reply})
                    st.rerun()

                else:
                    reply = "⚠️ I couldn't classify that. Try phrasing it as a task or a question."
                    st.session_state.chat.append({"role": "assistant", "text": reply})
                    st.rerun()

            except Exception as e:
                reply = f"❌ Could not reach Parent Agent ({PARENT_AGENT_URL}) — {e}"
                st.session_state.chat.append({"role": "assistant", "text": reply})
                st.rerun()
