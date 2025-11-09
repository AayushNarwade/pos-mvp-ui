import os
import html
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from notion_client import Client

# Optional (only used if GEMINI_API_KEY is set)
try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None

# ================== ENV ==================
load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY", "").strip()
DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()
PARENT_AGENT_URL = os.getenv("PARENT_AGENT_URL", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# ================== INIT ==================
st.set_page_config(page_title="POS-MVP", page_icon="⚡", layout="wide")
st.title("⚡ Present Operating System - MVP")
st.caption("Talk to your POS agent — tasks are auto-created in Notion; questions return concise research answers.")

# ---------- Environment warnings ----------
missing_env = []
if not NOTION_API_KEY:
    missing_env.append("NOTION_API_KEY")
if not DATABASE_ID:
    missing_env.append("NOTION_DATABASE_ID")
if not PARENT_AGENT_URL:
    missing_env.append("PARENT_AGENT_URL (backend /route endpoint)")
if missing_env:
    st.warning(
        "Missing environment variables: **" + ", ".join(missing_env) +
        "**. Set them in Render → **Environment** and redeploy."
    )

# Notion client (only if keys exist)
notion = Client(auth=NOTION_API_KEY) if NOTION_API_KEY else None

# Gemini model (optional, only if key provided)
use_research = bool(GEMINI_API_KEY and genai is not None)
if use_research:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        research_model = genai.GenerativeModel("gemini-1.5-flash-latest")
    except Exception as e:
        use_research = False
        st.warning(f"Research disabled — Gemini init failed: {e}")

# ================== STYLES ==================
st.markdown(
    """
<style>
.bubble {padding: 12px 14px; margin: 8px 0; border-radius: 14px; line-height: 1.45; font-size: 0.98rem;}
.user {background: #1f6feb20; border: 1px solid #1f6feb55; color: #e6edf3;}
.ai {background: #161b22; border: 1px solid #30363d; color: #c9d1d9;}
.small {font-size: 0.85rem; color: #8b949e;}
</style>
""",
    unsafe_allow_html=True,
)

def bubble(text: str, who: str = "user"):
    """Render a chat bubble."""
    text = html.escape(text).replace("\n", "<br>")
    cls = "user" if who == "user" else "ai"
    st.markdown(f'<div class="bubble {cls}">{text}</div>', unsafe_allow_html=True)

# ================== HELPERS ==================

def _safe(props: Dict[str, Any], key: str, path: List[Any]) -> Any:
    """Safely extract nested Notion properties."""
    try:
        val = props.get(key)
        if not val:
            return None
        for p in path:
            if isinstance(p, int):
                if isinstance(val, list) and len(val) > p:
                    val = val[p]
                else:
                    return None
            else:
                val = val.get(p) if isinstance(val, dict) else None
            if val is None:
                return None
        return val
    except Exception:
        return None

def _parse_iso(date_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        return None

@st.cache_data(ttl=30)
def fetch_tasks() -> Tuple[pd.DataFrame, str | None]:
    """Fetch tasks from Notion, support both Notion SDKs (v1 & v2)."""
    if not notion:
        return pd.DataFrame(), "Notion client is not configured."

    try:
        # Prefer v2 style first
        if hasattr(notion.databases, "query"):
            result = notion.databases.query(database_id=DATABASE_ID)
        else:
            # Fallback for older clients
            result = notion.databases.query(database_id=DATABASE_ID)


        rows = result.get("results", [])
        tasks = []
        for p in rows:
            props = p.get("properties", {})

            name = _safe(props, "Name", ["title", 0, "plain_text"]) or "—"
            status = _safe(props, "Status", ["select", "name"]) or "—"
            avatar = _safe(props, "Avatar", ["select", "name"]) or "—"
            xp = _safe(props, "XP", ["number"])
            due = _safe(props, "Due Date", ["date", "start"])

            tasks.append(
                {
                    "Task Name": name,
                    "Status": status,
                    "Avatar": avatar,
                    "XP": int(xp) if isinstance(xp, (int, float)) else None,
                    "Due Date": due,
                }
            )

        df = pd.DataFrame(tasks)

        # Sort by due date (soonest first); keep rows without a due date at bottom
        if not df.empty and "Due Date" in df.columns:
            df["_due_dt"] = df["Due Date"].apply(lambda s: _parse_iso(s) if isinstance(s, str) else None)
            df = df.sort_values(by=["_due_dt"], ascending=[True], na_position="last").drop(columns=["_due_dt"])

        return df, None

    except Exception as e:
        return pd.DataFrame(), str(e)

def add_task_to_notion(task_text: str) -> Tuple[bool, str | None]:
    """Create a simple task in Notion with sane defaults."""
    if not notion:
        return False, "Notion client is not configured."
    try:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                "Name": {"title": [{"text": {"content": task_text}}]},
                "Status": {"select": {"name": "To Do"}},
                "Avatar": {"select": {"name": "Producer"}},
                "XP": {"number": 0},
            },
        )
        return True, None
    except Exception as e:
        return False, str(e)

def research_answer(question: str) -> str:
    """Call Gemini and return a concise 1–2 sentence answer."""
    if not use_research:
        return "Research is disabled (missing or invalid GEMINI_API_KEY)."
    try:
        prompt = (
            "You are a concise research assistant. Answer the question in **one or two sentences**, "
            "focusing on direct facts. No prefaces, no markdown headers.\n\n"
            f"Question: {question}"
        )
        resp = research_model.generate_content(
            prompt,
            generation_config={"max_output_tokens": 384},
        )
        text = (resp.text or "").strip()
        return text if text else "I couldn't find a reliable answer."
    except Exception as e:
        return f"(research error) {e}"

# ================== TASK TABLE ==================
st.subheader("📋 Current Notion Tasks")

with st.spinner("Loading tasks from Notion…"):
    df, err = fetch_tasks()

if err:
    st.error(f"⚠️ Error fetching tasks: {err}")
elif df.empty:
    st.info("No tasks found in your Notion database.")
else:
    st.dataframe(df, use_container_width=True)

# ================== CHAT SECTION ==================
st.subheader("💬 Talk to POS Agent")

if "chat" not in st.session_state:
    st.session_state.chat = []  # [{"role": "user"/"assistant", "text": "..."}]

# Render history
for msg in st.session_state.chat:
    bubble(msg["text"], "user" if msg["role"] == "user" else "ai")

nl_input = st.text_input("Ask a question or say a task like 'remind me to call Priya at 6pm'")

c1, c2 = st.columns([1, 1])
send = c1.button("Send to POS")
clear = c2.button("Clear chat")

if clear:
    st.session_state.chat = []
    st.experimental_rerun()

if send and nl_input.strip():
    # Show user message
    st.session_state.chat.append({"role": "user", "text": nl_input})
    bubble(nl_input, "user")

    # Route via Parent Agent
    try:
        with st.spinner("Routing your message…"):
            r = requests.post(PARENT_AGENT_URL, json={"message": nl_input}, timeout=25)
            r.raise_for_status()
            routed = r.json()
    except Exception as e:
        reply = f"❌ Could not reach Parent Agent at `{PARENT_AGENT_URL}`.\n\n{e}"
        st.session_state.chat.append({"role": "assistant", "text": reply})
        bubble(reply, "ai")
    else:
        intent = routed.get("intent", "UNKNOWN")
        data = routed.get("data", nl_input)

        if intent == "TASK":
            with st.spinner("Creating task in Notion…"):
                ok, err = add_task_to_notion(data)
            if ok:
                reply = f"✅ Task added to Notion: “{data}”."
                # refresh cached table
                fetch_tasks.clear()
            else:
                reply = f"❌ Failed to add task: {err}"

            st.session_state.chat.append({"role": "assistant", "text": reply})
            bubble(reply, "ai")

        elif intent == "RESEARCH":
            with st.spinner("Researching…"):
                reply = research_answer(data)
            st.session_state.chat.append({"role": "assistant", "text": reply})
            bubble(reply, "ai")

        else:
            reply = "I couldn't classify that. Try phrasing it as a task (e.g., “remind me to…”) or a question."
            st.session_state.chat.append({"role": "assistant", "text": reply})
            bubble(reply, "ai")

st.markdown('<div class="small">Need to change keys/URLs? Update your Render '
            'environment variables and redeploy.</div>', unsafe_allow_html=True)
