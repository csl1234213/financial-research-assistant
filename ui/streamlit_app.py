import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from client.api_client import APIClient, APIClientError
from config.ui import (
    API_BASE_URL,
    PAGE_LAYOUT,
    PAGE_TITLE,
    UPLOAD_DIR,
)

client = APIClient(base_url=API_BASE_URL)

os.makedirs(UPLOAD_DIR, exist_ok=True)

# =========================
# Page Config
# =========================

st.set_page_config(
    page_title=PAGE_TITLE,
    layout=PAGE_LAYOUT,
)

st.title("📊 Financial Research Copilot")
st.caption("AI-powered multi-document financial analysis system")

# =========================
# Sidebar
# =========================

st.sidebar.title("🔎 Knowledge Sources")

try:
    knowledge = client.knowledge()
    pdf_files = knowledge["documents"]
    company_list = knowledge["companies"]
    doc_count = knowledge["document_count"]
except APIClientError:
    pdf_files = []
    company_list = []
    doc_count = 0

if pdf_files:

    selected_companies = st.sidebar.multiselect(
        "Select Companies",
        options=company_list,
        default=[]
    )

    st.sidebar.divider()

    st.sidebar.metric(
        "Documents",
        doc_count
    )

else:

    st.sidebar.info(
        "No document loaded"
    )
    selected_companies = []
# =========================
# Upload PDF
# =========================

st.sidebar.divider()
st.sidebar.subheader("Upload PDF")
uploaded_file = st.sidebar.file_uploader(
    "Upload PDF",
    type=["pdf"]
)

if uploaded_file:

    try:
        result = client.upload(
            uploaded_file.getvalue(),
            uploaded_file.name,
        )

        st.success(f"Uploaded: {result['file']}")
        st.success("Knowledge base updated")

        st.rerun()

    except Exception as e:
        st.error(f"Upload failed: {e}")
# =========================
# Question Input
# =========================

question = st.text_input(
    "Ask a question about companies or markets"
)

if st.button("Analyze", type="primary"):

    if not question:
        st.warning("Please enter a question")
    else:
        try:
            with st.spinner("🧠 AI is analyzing financial reports and building investment insights..."):
                selected_company = selected_companies[0] if selected_companies else None
                data = client.chat(
                    question=question,
                    company=selected_company,
                )

            report = data["report"]
            citations = data["citations"]
            reasoning = data["reasoning"]
            plan = data["plan"]
            execution_time = data["execution_time"]

            intent = reasoning["intent"]
            companies = reasoning["companies"]

            # =========================
            # Level 1: Research Scope (Product Understanding Layer)
            # =========================

            st.markdown("## 🧠 Research Scope")

            scope_text = f"""
**Intent:** `{reasoning['intent']}`

**Companies:** {reasoning['companies']}

**Evidence Count:** {reasoning['evidence_count']}

**Execution Time:** {execution_time}s
"""

            st.info(scope_text)

            st.markdown("## 📋 Execution Plan")
            for task in plan["tasks"]:
                task_type = task["step_type"]
                task_desc = task["description"]
                emoji = {"retrieve": "🔍", "compare": "⚖️", "synthesis": "🧩"}.get(task_type, "📌")
                st.caption(f"{emoji} **Step {task['step_id']}:** `{task_type}` — {task_desc}")

            # =========================
            # Intent Visualization (Sidebar)
            # =========================

            st.sidebar.divider()
            st.sidebar.markdown("## 🧭 Intent Analysis")

            if intent == "SINGLE_COMPANY":
                st.sidebar.success("🟢 Single Company Analysis")
            elif intent == "COMPARE_COMPANIES":
                st.sidebar.info("🔵 Comparative Analysis")
            elif intent == "GLOBAL_RESEARCH":
                st.sidebar.warning("🟣 Global Research Mode")
            else:
                st.sidebar.error("⚪ Unknown Intent")

            if companies:
                st.sidebar.markdown("**Companies:**")
                for c in companies:
                    st.sidebar.write(f"- {c}")

            st.divider()

            # =========================
            # Level 2: Answer Report (Result Layer)
            # =========================

            st.markdown("## 📊 Investment Research Report")
            st.markdown(report)

            st.divider()

            # =========================
            # Level 3: Evidence (Citation Layer)
            # =========================

            st.markdown("## 📎 Evidence")

            if citations:
                for c in citations:
                    with st.container():
                        st.markdown(f"""
**[{c['rank']}] {c['source']}**

- Chunk ID: `{c['chunk_id']}`
- Score: `{c['similarity']}`

> {c['preview']}
""")
                        st.divider()
            else:
                st.warning("No relevant evidence found")

        except APIClientError:
            st.error(
                f"⚠️ API server not reachable at {API_BASE_URL}. "
                "Please start the API server first:\n\n```\nuvicorn api.app:app --reload\n```"
            )
        except Exception as e:
            st.error(f"Analysis failed: {e}")
            import traceback
            st.code(traceback.format_exc())

if not doc_count:
    st.info("Please upload at least one PDF document to get started")
