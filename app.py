import streamlit as st
import os
import io
import sqlite3
from dotenv import load_dotenv
from groq import Groq
from docx import Document
from pypdf import PdfReader

# Load your API key from .env
load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=60.0)

st.title("🧑‍🏫 Teacher Assistant")
st.caption("Ask me to make a lesson plan, quiz, assignment, or report card comment")

# ---------- Database setup (saves chat history to a local file) ----------
DB_PATH = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def load_messages():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, role, content FROM messages ORDER BY id ASC").fetchall()
    conn.close()
    return [{"id": r[0], "role": r[1], "content": r[2]} for r in rows]

def save_message(role, content):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("INSERT INTO messages (role, content) VALUES (?, ?)", (role, content))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def update_message(msg_id, content):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE messages SET content = ? WHERE id = ?", (content, msg_id))
    conn.commit()
    conn.close()

def clear_all_messages():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM messages")
    conn.commit()
    conn.close()

init_db()

# ---------- Session state setup ----------
if "messages" not in st.session_state:
    st.session_state.messages = load_messages()  # load saved history on first run

if "mode" not in st.session_state:
    st.session_state.mode = None  # which form is currently open

# ---------- Helper: turn AI text into a downloadable Word doc ----------
def text_to_docx_bytes(text):
    doc = Document()
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=1)
        elif stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            p = doc.add_paragraph()
            p.add_run(stripped[2:-2]).bold = True
        else:
            doc.add_paragraph(line)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# ---------- Helper: read text out of an uploaded file ----------
def read_uploaded_file(uploaded_file):
    if uploaded_file.name.endswith(".docx"):
        doc = Document(uploaded_file)
        return "\n".join(p.text for p in doc.paragraphs)
    elif uploaded_file.name.endswith(".pdf"):
        reader = PdfReader(uploaded_file)
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return "\n".join(text_parts)
    else:  # assume plain text
        return uploaded_file.read().decode("utf-8", errors="ignore")

# ---------- Sidebar: chat history controls ----------
with st.sidebar:
    st.header("Chat History")
    st.caption(f"{len(st.session_state.messages)} messages saved")
    if st.button("🗑️ Clear Chat History"):
        clear_all_messages()
        st.session_state.messages = []
        st.rerun()

# ---------- Quick action buttons ----------
st.write("**Quick actions:**")
col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    if st.button("📝 Lesson Plan"):
        st.session_state.mode = "lesson_plan"

with col2:
    if st.button("❓ Quiz / Test"):
        st.session_state.mode = "quiz"

with col3:
    if st.button("📋 Assignment"):
        st.session_state.mode = "assignment"

with col4:
    if st.button("💬 Report Comment"):
        st.session_state.mode = "comment"

with col5:
    if st.button("📄 Summarize Doc"):
        st.session_state.mode = "summarize"

with col6:
    if st.button("📓 Generate Notes"):
        st.session_state.mode = "notes"

quick_prompt = None  # will hold the built prompt once a form is submitted

# ---------- Lesson Plan form ----------
if st.session_state.mode == "lesson_plan":
    with st.form("lesson_plan_form"):
        st.subheader("Lesson Plan Details")
        subject = st.text_input("Subject", placeholder="e.g. Design and Technology")
        topic = st.text_input("Topic / Sub-topic", placeholder="e.g. 2.1 Materials and Manufacturing - Heat Treatment")
        grade = st.text_input("Class / Grade", placeholder="e.g. Form 2")
        duration = st.selectbox("Duration", ["40 Minutes", "80 Minutes", "120 Minutes"])
        submitted = st.form_submit_button("Generate Lesson Plan")

        if submitted:
            quick_prompt = f"""Create a full lesson plan using this exact structure:

Header fields: Name of Teacher (leave blank), Date (leave blank), Class: {grade}, Duration: {duration}, Subject: {subject}, Topic: {topic}, Sub-topic, General Competence(s), Lesson Goal, Specific Competences, Rationale, Prior Knowledge, References, Learning Environment, Teaching and Learning Materials/Resources, Expected Standard.

Then a Lesson Progression table with 4 columns (Stages | Teacher's Role | Learners' Role | Assessment Criteria) with these stages:
- Introduction (10 mins): a short real-world scenario/question to hook learners, followed by discussion
- Lesson Development (50 mins): numbered teaching steps including a demonstration and a hands-on learner task
- Exercise/Assessment (15 mins): an individual task with clear criteria
- Homework: one short task or question
- Conclusion (5 mins): a recap and a review question

End with a Lesson Evaluation section (Challenges / Teacher's response) left blank for after the lesson.

Subject: {subject}
Topic: {topic}
Class: {grade}"""

# ---------- Quiz / Test form ----------
elif st.session_state.mode == "quiz":
    with st.form("quiz_form"):
        st.subheader("Quiz / Test Details")
        subject = st.text_input("Subject", placeholder="e.g. Chemistry")
        topics = st.text_input("Topics to include (comma-separated)", placeholder="e.g. Periodic table, Atomic structure")
        num_questions = st.number_input("Number of questions", min_value=1, max_value=40, value=10)
        question_types = st.multiselect(
            "Question types to include",
            ["Multiple Choice", "Structured / Short Answer", "Essay (choose 1 of a few)"],
            default=["Multiple Choice", "Structured / Short Answer"]
        )
        difficulty = st.selectbox("Difficulty", ["Easy", "Medium", "Hard", "Mixed"])
        submitted = st.form_submit_button("Generate Quiz / Test")

        if submitted:
            quick_prompt = f"""Create a test/quiz using this exact structure, matching a formal school exam paper:

Header: School name placeholder, Department, Subject: {subject}, Form/Class placeholder, Test name, Duration placeholder, Name field, Total marks.

Instructions block: number of sections, how to answer, any special instructions (e.g. use of drafting tools if relevant).

Then organize into sections based on the question types requested: {', '.join(question_types)}.
- Multiple Choice section: format each question exactly like this style (NOT a table):
  1) [question text]
  * A) [option]
  * B) [option]
  * C) [option]
  * D) [option]
  Each question worth 1 mark. Do NOT mark the correct answer inline — put all correct answers together in an Answer Key at the very end.
- Structured/Short Answer section: numbered questions with lettered sub-parts (a), (b), (c), each with a mark allocation in brackets like [2].
- Essay section (if included): present a few options and instruct the student to answer only one, worth more marks (e.g. [20]).

Include an Answer Key at the very end, separate from the questions.

Subject: {subject}
Topics to cover: {topics}
Number of questions: {num_questions}
Difficulty: {difficulty}"""

# ---------- Assignment form ----------
elif st.session_state.mode == "assignment":
    with st.form("assignment_form"):
        st.subheader("Assignment Details")
        subject = st.text_input("Subject", placeholder="e.g. Design and Technology")
        topics = st.text_input("Topics / Scenarios to cover (comma-separated)", placeholder="e.g. Heat treatment, Holding tools, Plastics")
        duration = st.text_input("Duration to complete", placeholder="e.g. 3 weeks")
        due_date = st.text_input("Due date", placeholder="e.g. 7th September, 2026")
        submitted = st.form_submit_button("Generate Assignment")

        if submitted:
            quick_prompt = f"""Create an assignment using this exact structure:

Header: School/Department placeholder, Subject: {subject}, Duration: {duration}, Due Date: {due_date}, Name field.

Instructions block: number of sections, answer-all instruction, any special notes (e.g. use of drafting tools for graphics sections).

Then organize into scenario-based tasks — for each topic listed, write:
- A short real-world Scenario paragraph setting up a practical problem
- A TASK section with numbered/lettered sub-questions, each with a mark allocation in brackets like [2]
- Include a mix of short-answer, listing, explaining, and (where relevant to the subject) a drawing/sketching task

If the subject involves drafting or graphics, add a final section instructing students to complete that part on A3 paper.

Subject: {subject}
Topics/Scenarios: {topics}"""

# ---------- Report Comment (simple, no form) ----------
elif st.session_state.mode == "comment":
    quick_prompt = "Write a report card comment. Ask me for the student's grade/performance level and any behavior notes if I haven't given them yet."
    st.session_state.mode = None  # reset immediately since no form needed

# ---------- Generate Notes form ----------
elif st.session_state.mode == "notes":
    with st.form("notes_form"):
        st.subheader("Generate Notes")
        subject = st.text_input("Subject", placeholder="e.g. Chemistry")
        topic = st.text_input("Topic / Sub-topic", placeholder="e.g. Periodic Table and Electron Configuration")
        grade = st.text_input("Class / Grade", placeholder="e.g. Form 1")
        depth = st.selectbox("Level of detail", ["Brief overview", "Standard (exam-ready)", "In-depth / detailed"])
        note_format = st.selectbox("Format", ["Bullet points", "Structured with headings and sub-points", "Numbered outline"])
        submitted = st.form_submit_button("Generate Notes")

        if submitted:
            quick_prompt = f"""Create clear, well-organized study notes for learners.

Subject: {subject}
Topic / Sub-topic: {topic}
Class / Grade level: {grade}
Level of detail: {depth}
Format: {note_format}

Structure the notes with:
- A short introduction explaining what the topic covers and why it matters
- Key definitions and terms clearly explained
- Main concepts broken into clearly labeled sections
- Simple examples or real-world applications where relevant
- A short summary/recap at the end (3-5 key takeaways)

Keep the language appropriate for the stated class/grade level. Use markdown headings and bullet points for readability."""

# ---------- Summarize Document form ----------
elif st.session_state.mode == "summarize":
    with st.form("summarize_form"):
        st.subheader("Summarize a Document")
        uploaded_file = st.file_uploader("Upload a .docx, .pdf, or .txt file", type=["docx", "pdf", "txt"])
        length = st.selectbox("Summary length", ["Short (a few sentences)", "Medium (a paragraph)", "Detailed (key points list)"])
        submitted = st.form_submit_button("Summarize")

        if submitted and uploaded_file is not None:
            file_text = read_uploaded_file(uploaded_file)
            if not file_text.strip():
                st.warning("Couldn't find any readable text in this file. If it's a scanned PDF (a photo of a page rather than typed text), text extraction won't work — try a typed/digital document instead.")
            else:
                # keep prompts fast — trim very long documents
                file_text = file_text[:12000]
                quick_prompt = f"""Summarize the following document for a busy teacher. Summary length: {length}.

Document:
\"\"\"
{file_text}
\"\"\""""
        elif submitted and uploaded_file is None:
            st.warning("Please upload a file first.")

# ---------- Show past messages (with download/edit for assistant replies) ----------
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            edit_key = f"edit_mode_{i}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = False

            if st.session_state[edit_key]:
                edited_text = st.text_area("Edit this document:", value=msg["content"], height=300, key=f"textarea_{i}")
                if st.button("💾 Save changes", key=f"save_{i}"):
                    st.session_state.messages[i]["content"] = edited_text
                    if "id" in msg:
                        update_message(msg["id"], edited_text)
                    st.session_state[edit_key] = False
                    st.rerun()
            else:
                st.write(msg["content"])

            btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 3])
            with btn_col1:
                if st.button("✏️ Edit", key=f"edit_btn_{i}"):
                    st.session_state[edit_key] = True
                    st.rerun()
            with btn_col2:
                docx_buffer = text_to_docx_bytes(msg["content"])
                st.download_button(
                    "⬇️ Download .docx",
                    data=docx_buffer,
                    file_name=f"document_{i}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"download_{i}"
                )
        else:
            st.write(msg["content"])

# ---------- Input box at the bottom ----------
user_input = st.chat_input("What do you need help with today?")

# If a form was just submitted, use that prompt instead
if quick_prompt:
    user_input = quick_prompt
    st.session_state.mode = None  # close the form after submitting

if user_input:
    # Show the user's message and save it to the database
    user_msg_id = save_message("user", user_input)
    st.session_state.messages.append({"id": user_msg_id, "role": "user", "content": user_input})
    with st.chat_message("user"):
        st.write(user_input)

    # Send it to Groq and show the reply
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response = client.chat.completions.create(
                    model="openai/gpt-oss-120b",
                    max_tokens=2000,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant for teachers. You help create lesson plans, tests, quizzes, assignments, grading rubrics, report card comments, and document summaries. Follow any structural instructions given exactly and precisely. Be practical, clear, and well-formatted using markdown headings and tables where appropriate."},
                        {"role": "user", "content": user_input}
                    ]
                )
                reply = response.choices[0].message.content
                st.write(reply)
            except Exception as e:
                reply = f"Sorry, something went wrong: {e}"
                st.error(reply)

    # Save the reply to the database and history
    assistant_msg_id = save_message("assistant", reply)
    st.session_state.messages.append({"id": assistant_msg_id, "role": "assistant", "content": reply})
    st.rerun()