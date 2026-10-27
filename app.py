from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
import os
import re
import socket
import hashlib
import binascii
import uuid
import time
import traceback
import libsql_client
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from groq import Groq
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from curriculum import CURRICULA, DURATIONS, SUBJECTS, TOPICS
from lesson_docx import schema

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# A blunt but effective safety net: without this, a database or network hiccup could
# hang a request indefinitely with no error at all. 10 seconds is generous enough for
# a slow connection, but short enough that a user isn't stuck waiting forever.
socket.setdefaulttimeout(10)

import sys as _sys
_groq_file = getattr(_sys.modules.get("groq"), "__file__", None)
if _groq_file and os.path.abspath(_groq_file).startswith(BASE_DIR):
    print("WARNING: a local groq.py is hiding the real Groq package. Delete it and run: pip install groq")

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")


# ---------------------------------------------------------------------------
# File uploads
# ---------------------------------------------------------------------------
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {
    # Images
    "png", "jpg", "jpeg", "gif", "webp", "svg",
    # Documents
    "pdf", "doc", "docx", "txt", "rtf", "xls", "xlsx", "csv",
    # Presentations / spreadsheets (OpenDocument)
    "odp", "ods",
}
ALLOWED_MIME_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain", "text/csv",
}
MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))


def allowed_file(filename):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def allowed_content_type(content_type):
    return content_type.split(";")[0].strip().lower() in ALLOWED_MIME_TYPES


def get_upload_path(filename):
    """Store files under a per-user folder so imports are private by default."""
    uid = session.get("user_id")
    folder = str(uid) if uid else "shared"
    folder_path = os.path.join(UPLOAD_FOLDER, folder)
    os.makedirs(folder_path, exist_ok=True)
    # Guard against path traversal in the filename
    safe = os.path.basename(filename)
    return os.path.join(folder_path, safe)


def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Copy .env.example to .env and fill in the value before starting the app."
        )
    return value


client = None
groq_client = None


def get_gemini_client():
    global client
    if client is not None:
        return client
    try:
        client = genai.Client(api_key=require_env("GEMINI_API_KEY"))
        return client
    except Exception as exc:
        print(f"Warning: Gemini client could not be initialized: {exc}")
        return None


def get_groq_client():
    global groq_client
    if groq_client is not None:
        return groq_client
    try:
        if not os.getenv("GROQ_API_KEY"):
            return None
        groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        return groq_client
    except Exception as exc:
        print(f"Warning: Groq client could not be initialized: {exc}")
        return None


def looks_like_quota_error(exc):
    text = str(exc).lower()
    return any(token in text for token in ["resource_exhausted", "quota", "429", "rate limit", "exceeded your current quota"])

SYSTEM_INSTRUCTION = (
    "You are a helpful assistant for teachers. You help create lesson plans, "
    "quizzes, grading rubrics, and report card comments. Be practical and concise."
)

# Gemini model IDs, tried in order. Google retires models regularly (gemini-2.5-flash is
# scheduled to shut down on 16 Oct 2026), so GEMINI_MODEL in .env can override the first
# choice without a code change. If a model is gone (404) or out of quota, the next one is tried.
GEMINI_MODELS = []
for _name in [os.getenv("GEMINI_MODEL"), "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]:
    if _name and _name not in GEMINI_MODELS:
        GEMINI_MODELS.append(_name)
MODEL_NAME = GEMINI_MODELS[0]


def _is_model_missing_error(exc):
    text = str(exc).lower()
    return any(t in text for t in ["404", "not found", "no longer available", "decommission", "does not exist"])


def _is_permanent_ai_error(exc):
    """Errors where sending the same request again will not help, so don't wait and retry."""
    text = str(exc).lower()
    return (looks_like_quota_error(exc) or _is_model_missing_error(exc)
            or any(t in text for t in ["api key", "api_key", "permission", "401", "403", "invalid argument"]))


_retry_transient = retry(
    stop=stop_after_attempt(2), wait=wait_fixed(1),
    retry=retry_if_exception(lambda e: not _is_permanent_ai_error(e)), reraise=True,
)


@_retry_transient
def _gemini_call(client, model, contents, config):
    kwargs = {"model": model, "contents": contents}
    if config is not None:
        kwargs["config"] = config
    response = client.models.generate_content(**kwargs)
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini returned an empty response")
    return text


def _gemini_generate(client, contents, json_mode=False):
    # No temperature/top_p/top_k: Gemini 3.x ignores them and may reject them.
    config = genai_types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=8192) if json_mode else None
    last_exc = None
    for model in GEMINI_MODELS:
        try:
            return _gemini_call(client, model, contents, config)
        except Exception as exc:
            last_exc = exc
            if _is_model_missing_error(exc) or looks_like_quota_error(exc):
                print(f"Gemini model {model!r} unavailable, trying the next one: {str(exc)[:200]}")
                continue
            raise
    raise last_exc or RuntimeError("No Gemini model was available")


def call_gemini_with_retry(client, user_message):
    """Chat replies (plain text)."""
    return _gemini_generate(client, user_message)


def call_gemini_json(client, prompt):
    """Lesson plans, notes, assignments and tests (the model is asked for JSON)."""
    return _gemini_generate(client, prompt, json_mode=True)


def build_chat_prompt(new_user_message, prior_messages=None):
    prior_messages = prior_messages or []
    lines = [SYSTEM_INSTRUCTION]
    if prior_messages:
        lines.append("\nPrevious conversation:")
        for item in prior_messages:
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()[:1500]
            if not content:
                continue
            if role == "user":
                lines.append(f"Teacher: {content}")
            elif role == "assistant":
                lines.append(f"Assistant: {content}")
    lines.append(f"\nTeacher's latest request: {new_user_message}")
    return "\n".join(lines)


def _groq_model_candidates():
    # llama-3.3-70b-versatile and llama-3.1-8b-instant were shut down by Groq on 16 Aug 2026.
    # GROQ_MODEL in .env is tried first if you set it; otherwise the replacements below.
    candidates = []
    for name in [os.getenv("GROQ_MODEL"), "openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
        if name and name not in candidates:
            candidates.append(name)
    return candidates


def _groq_should_try_next_model(exc):
    text = str(exc).lower()
    return any(t in text for t in ["404", "not found", "decommission", "does not exist", "model_not_found",
                                   "429", "rate limit", "rate_limit", "too many requests"])


def call_groq_with_text(prompt, json_mode=False):
    client = get_groq_client()
    if client is None:
        raise RuntimeError("Groq is not configured")

    if json_mode and "json" not in prompt.lower():
        prompt += "\n\nReturn only valid JSON."

    last_exc = None
    for model in _groq_model_candidates():
        kwargs = {"model": model, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3, "max_tokens": 8192}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content
            if not text:
                raise RuntimeError("Groq returned an empty response")
            return text
        except Exception as exc:
            last_exc = exc
            if _groq_should_try_next_model(exc):
                print(f"Groq model {model!r} unavailable, trying the next one: {str(exc)[:200]}")
                continue
            raise
    raise last_exc or RuntimeError("No Groq model was available")


def _offline_chat_reply(user_message):
    topic = (user_message or "lesson support").strip() or "lesson support"
    topic = topic[:120]
    return (
        "I’m running in offline demo mode because the external AI service is unavailable. "
        f"For your request about '{topic}', a practical approach is to: 1) state the learning objective, "
        "2) teach the key idea with one example, 3) check understanding with a quick question, and "
        "4) give a short task for learners to complete."
    )


def _extract_prompt_value(prompt, key, fallback=""):
    if not prompt:
        return fallback
    patterns = [
        rf"{re.escape(key)}:\s*(.*?)(?:\n|$)",
        rf"{re.escape(key)}\s*[:\-]\s*(.*?)(?:\n|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, prompt, flags=re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1).strip()
            value = re.sub(r"\s*\.+\s*$", "", value)
            if value:
                return value
    return fallback


def _offline_fallback_json_from_prompt(prompt):
    prompt = prompt or ""
    subject = _extract_prompt_value(prompt, "Subject", "ICT")
    class_name = _extract_prompt_value(prompt, "Class", "Form 1")
    topic = _extract_prompt_value(prompt, "Topic / sub-topic") or _extract_prompt_value(prompt, "Topic", "Computer Basics")
    duration_match = re.search(r"Lesson length:\s*(\d+)", prompt, flags=re.IGNORECASE)
    duration = int(duration_match.group(1)) if duration_match else 40
    completion_window = _extract_prompt_value(prompt, "Completion window", f"{duration} minutes")
    due_date = _extract_prompt_value(prompt, "Due date", "Not specified")
    lowered = prompt.lower()

    if "assignment" in lowered:
        return json.dumps({
            "title": f"{subject}: {topic}",
            "instructions": f"Use the ideas related to {topic} and complete the assignment for {class_name}. Submit clearly and show your work.",
            "questions": f"1. Explain the main idea behind {topic}.\n2. Give a practical example.\n3. Present a short written response using relevant terminology.",
            "rubric": "Understanding 5 marks, Application 3 marks, Presentation 2 marks.",
            "marking_guide": "Award marks for accuracy, clarity, and completion.",
            "summary": f"{subject} assignment on {topic} for {class_name}.",
            "teacher_notes": f"Completion window: {completion_window}. Due date: {due_date}.",
        }, ensure_ascii=False)

    if "test" in lowered:
        return json.dumps({
            "title": f"{subject} Test: {topic}",
            "instructions": f"Answer all questions on {topic} for {class_name}. Show working where needed.",
            "questions": f"1. Define {topic}.\n2. Give two key points.\n3. Answer one structured question with examples.",
            "rubric": "Knowledge 5 marks, Application 3 marks, Explanation 2 marks.",
            "marking_guide": "Check correctness, clarity, and relevance to the topic.",
            "summary": f"{subject} test based on {topic}.",
            "teacher_notes": f"Completion window: {completion_window}. Due date: {due_date}.",
        }, ensure_ascii=False)

    if "notes" in lowered:
        return json.dumps({
            "title": f"{subject}: {topic}",
            "summary": f"Key notes for {subject} based on {topic}.",
            "main_points": f"- Understand the main idea behind {topic}.\n- Add one example or explanation.\n- Summarise the lesson in learners' words.",
            "key_terms": "topic\nexample\nsummary\napplication",
            "teacher_notes": f"Completion window: {completion_window}. Due date: {due_date}.",
            "instructions": "Use clear headings and concise school-style notes.",
        }, ensure_ascii=False)

    return json.dumps(_offline_lesson_plan(subject=subject or "ICT", class_name=class_name or "Form 1", topic=topic or "Computer Basics", duration=int(duration or 40), subtopic="Core concept"), ensure_ascii=False)


def _offline_lesson_plan(subject="ICT", class_name="Form 1", topic="Computer Basics", duration=40, subtopic="Input and output devices"):
    return {
        "topic": topic,
        "subtopic": subtopic or "Core concept",
        "general_competences": "Critical thinking, Collaboration, Communication",
        "lesson_goal": f"By the end of the lesson, learners will be able to explain the key ideas behind {topic.lower()} and apply them in a classroom activity.",
        "specific_competences": "- Identify the main parts or ideas related to the topic.\n- Explain the concept in their own words.\n- Apply the concept to a short classroom activity.",
        "rationale": "The lesson helps learners build practical understanding of the topic and connect classroom learning to everyday use.",
        "prior_knowledge": "Learners know how to participate in classroom discussion and use basic classroom materials.",
        "references": "Teacher's notes, textbook, classroom examples.",
        "learning_environment": "Normal classroom with chalkboard or whiteboard and simple visual aids.",
        "materials": "Board, markers, charts, learner notebooks, projector if available.",
        "expected_standard": "Learners can describe the key idea and answer a simple question about it correctly.",
        "stages": {
            "introduction": {
                "teacher": "Ask learners what they already know about the topic and connect it to real life.",
                "learners": "Share prior knowledge and respond to simple questions.",
                "assessment": "Ask 2-3 quick oral questions to check understanding."
            },
            "development": {
                "teacher": "Explain the main idea clearly with examples and a short demonstration.",
                "learners": "Listen, take notes, and ask questions where needed.",
                "assessment": "Check whether learners can explain the key idea in their own words."
            },
            "exercise": {
                "teacher": "Give a short class task or exercise based on the topic.",
                "learners": "Work individually or in pairs to complete the activity.",
                "assessment": "Review learner answers and correct misconceptions."
            },
            "homework": {
                "teacher": "Assign a brief follow-up task to reinforce the concept.",
                "learners": "Complete the written task in their notebooks.",
                "assessment": "Check the homework for accuracy and understanding."
            },
            "conclusion": {
                "teacher": "Summarise the lesson and reinforce the key points.",
                "learners": "State one thing they learned and one question they still have.",
                "assessment": "Use a brief exit question to confirm learning."
            }
        }
    }


def _offline_lesson_plan_from_request(layout, subject, class_name, topic, subtopic, duration):
    # Ensure the fallback matches the same structure the actual lesson-plan route expects.
    return _offline_lesson_plan(subject=subject or "ICT", class_name=class_name or "Form 1", topic=topic or "Computer Basics", duration=int(duration or 40), subtopic=subtopic or "Core concept")


def generate_ai_reply_with_status(prompt, topic_hint=""):
    """Returns (reply_text, is_offline). Gemini first, then Groq, then a labelled offline reply."""
    gemini_client = get_gemini_client()
    if gemini_client is not None:
        try:
            return call_gemini_with_retry(gemini_client, prompt), False
        except Exception as exc:
            print("Gemini failed, trying Groq:", repr(exc)[:300])

    try:
        return call_groq_with_text(prompt), False
    except Exception as exc:
        print("Groq failed, using the offline chat reply:", repr(exc)[:300])
        return _offline_chat_reply(topic_hint or "your request"), True


def generate_ai_reply(user_message):
    return generate_ai_reply_with_status(user_message)[0]


# ---------- Database (Turso) ----------
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")


def _new_raw_client():
    if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
        raise RuntimeError(
            "Missing Turso configuration. Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN "
            "in the environment before using the database."
        )
    connect_url = TURSO_DATABASE_URL.replace("libsql://", "https://")
    return libsql_client.create_client_sync(url=connect_url, auth_token=TURSO_AUTH_TOKEN)


_DB_ATTEMPTS = 3


def _is_transient_db_error(exc):
    text = (type(exc).__name__ + " " + str(exc)).lower()
    return any(t in text for t in ["disconnect", "connection", "timeout", "timed out", "reset by peer", "eof",
                                   "temporarily", "bad gateway", "gateway", "unavailable", "502", "503", "504", "ssl"])


class _RetryingDB:
    """Opens a fresh connection for every statement, closes it afterwards, and tries again a
    couple of times if the connection drops ("Server disconnected"). Before this, clients were
    never closed, so stale connections piled up and later requests failed on them."""

    def execute(self, sql, args=None):
        last = None
        for attempt in range(_DB_ATTEMPTS):
            try:
                with _new_raw_client() as raw:
                    return raw.execute(sql, args) if args is not None else raw.execute(sql)
            except Exception as exc:
                last = exc
                if attempt < _DB_ATTEMPTS - 1 and _is_transient_db_error(exc):
                    print(f"Database connection problem ({type(exc).__name__}: {str(exc)[:120]}); retrying...")
                    time.sleep(0.7 * (attempt + 1))
                    continue
                raise
        raise last


def get_db_client():
    return _RetryingDB()


_db_ready = False


def init_db():
    global _db_ready
    if _db_ready:
        return
    db = get_db_client()
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # conversations and messages for persistent chat
    db.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            title TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)



    # Imported images and documents (images, PDFs, Word docs, spreadsheets, etc.)
    db.execute("""CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            file_type TEXT NOT NULL,          -- 'image', 'pdf', 'docx', 'spreadsheet', ...
            mime_type TEXT,
            extension TEXT,
            file_path TEXT NOT NULL,          -- relative to UPLOAD_FOLDER
            file_size INTEGER,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, title)
        )""")
    _db_ready = True


def create_conversation(user_id, title="New conversation"):
    db = get_db_client()
    conv_id = uuid.uuid4().hex
    db.execute("INSERT INTO conversations (id, user_id, title) VALUES (?, ?, ?)", [conv_id, user_id, title])
    return conv_id


def save_message(conversation_id, role, content):
    db = get_db_client()
    db.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)", [conversation_id, role, content])


def get_conversations_for_user(user_id):
    db = get_db_client()
    rows = db.execute("SELECT id, title, created_at FROM conversations WHERE user_id = ? ORDER BY created_at DESC", [user_id]).rows
    return [{"id": r[0], "title": r[1], "created_at": r[2]} for r in rows]


def get_messages_for_conversation(conversation_id):
    db = get_db_client()
    rows = db.execute("SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id", [conversation_id]).rows
    return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]


# ---------- Password hashing (same approach as the original Streamlit app) ----------
def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return binascii.hexlify(dk).decode(), binascii.hexlify(salt).decode()


def verify_password(password, stored_hash, stored_salt):
    salt = binascii.unhexlify(stored_salt)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return binascii.hexlify(dk).decode() == stored_hash


def create_user(full_name, email, password):
    init_db()
    db = get_db_client()
    existing = db.execute("SELECT id FROM users WHERE email = ?", [email]).rows
    if existing:
        return None  # email already registered
    pw_hash, salt = hash_password(password)
    result = db.execute(
        "INSERT INTO users (full_name, email, password_hash, salt) VALUES (?, ?, ?, ?)",
        [full_name, email, pw_hash, salt]
    )
    return result.last_insert_rowid


def authenticate_user(email, password):
    init_db()
    db = get_db_client()
    rows = db.execute(
        "SELECT id, full_name, password_hash, salt FROM users WHERE email = ?", [email]
    ).rows
    if not rows:
        return None
    user_id, full_name, pw_hash, salt = rows[0]
    if verify_password(password, pw_hash, salt):
        return {"id": user_id, "full_name": full_name}
    return None


# ---------- Auth routes ----------
@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("chat_page"))
    return render_template("login.html", show_register=False, error=None)


@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    try:
        user = authenticate_user(email, password)
    except Exception as e:
        return render_template("login.html", show_register=False, error=f"Couldn't reach the database: {e}")

    if not user:
        return render_template("login.html", show_register=False, error="Incorrect email or password.")

    session["user_id"] = user["id"]
    session["full_name"] = user["full_name"]
    return redirect(url_for("chat_page"))


@app.route("/register", methods=["POST"])
def register():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not full_name or not email or not password:
        return render_template("login.html", show_register=True, error="Please fill in every field.")
    if len(password) < 6:
        return render_template("login.html", show_register=True, error="Password should be at least 6 characters.")

    try:
        new_user_id = create_user(full_name, email, password)
    except Exception as e:
        return render_template("login.html", show_register=True, error=f"Couldn't reach the database: {e}")

    if not new_user_id:
        return render_template("login.html", show_register=True, error="That email is already registered.")

    session["user_id"] = new_user_id
    session["full_name"] = full_name
    return redirect(url_for("chat_page"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------- Chat routes (all require login) ----------
@app.route("/chat")
def chat_page():
    if not session.get("user_id"):
        return redirect(url_for("index"))
    user_id = session.get("user_id")
    # ensure DB tables exist
    init_db()
    # select or create current conversation
    if "current_conversation" not in session:
        convs = get_conversations_for_user(user_id)
        if convs:
            session["current_conversation"] = convs[0]["id"]
        else:
            session["current_conversation"] = create_conversation(user_id, "New conversation")
    messages = get_messages_for_conversation(session["current_conversation"])
    cfg = {"curricula": CURRICULA, "subjects": SUBJECTS, "durations": DURATIONS, "topics": TOPICS, "schema": schema()}
    return render_template("chat.html", messages=messages, full_name=session.get("full_name", ""), cfg=cfg)


MAX_HISTORY_MESSAGES = 12  # how many earlier messages the AI sees


@app.route("/send", methods=["POST"])
def send():
    if not session.get("user_id"):
        return jsonify({"error": "Please log in again."}), 401

    user_message = ((request.get_json(silent=True) or {}).get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Chat history lives in the database. (Keeping it in the session cookie overflows the
    # ~4 KB browser limit after a few replies, which logs the teacher out.)
    conv_id = session.get("current_conversation")
    prior = []
    try:
        if not conv_id:
            conv_id = create_conversation(session["user_id"], "New conversation")
            session["current_conversation"] = conv_id
        prior = get_messages_for_conversation(conv_id)[-MAX_HISTORY_MESSAGES:]
        save_message(conv_id, "user", user_message)
    except Exception as e:
        print("Could not load/save chat history:", repr(e))
        conv_id = None

    prompt = build_chat_prompt(user_message, prior)
    try:
        reply, is_offline = generate_ai_reply_with_status(prompt, topic_hint=user_message)
    except Exception as e:
        reply, is_offline = f"Sorry, something went wrong: {e}", True

    if conv_id and not is_offline:  # don't store offline placeholders as if they were real answers
        try:
            save_message(conv_id, "assistant", reply)
        except Exception as e:
            print("Could not save the reply:", repr(e))

    return jsonify({"reply": reply})


@app.route("/clear", methods=["POST"])
def clear():
    if not session.get("user_id"):
        return jsonify({"error": "Please log in again."}), 401
    # create a new conversation for the user and switch to it
    user_id = session.get("user_id")
    init_db()
    conv_id = create_conversation(user_id, "New conversation")
    session["current_conversation"] = conv_id
    return jsonify({"status": "cleared", "conversation_id": conv_id})

# ---------- File import routes (require login) ----------
@app.route("/import", methods=["POST"])
def import_file():
    """Upload an image or document for later use in lesson plans, notes, etc."""
    if not session.get("user_id"):
        return jsonify({"error": "Please log in again."}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file field found."}), 400

    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "No file selected."}), 400

    if not allowed_file(f.filename):
        return jsonify({"error": "File type not allowed. Upload images, PDFs, Word docs, or spreadsheets."}), 400

    if not allowed_content_type(f.mimetype):
        return jsonify({"error": "File content type not allowed."}), 400

    # Enforce a soft size limit from the client-side; Flask also enforces MAX_CONTENT_LENGTH
    try:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(0)
    except Exception:
        size = 0
    max_bytes = MAX_CONTENT_LENGTH or (25 * 1024 * 1024)
    if size > max_bytes:
        return jsonify({"error": f"File too large. Maximum size is {max_bytes} bytes."}), 400

    # Build a title and a safe filename
    title = request.form.get("title", "").strip()
    if not title:
        ext = f.filename.rsplit(".", 1)[1].lower() if "." in f.filename else ""
        title = f"Imported {ext if ext else 'file'} {uuid.uuid4().hex[:6]}"

    # Use a unique filename to avoid collisions
    ext = f.filename.rsplit(".", 1)[1].lower() if "." in f.filename else ""
    stored_name = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    upload_path = get_upload_path(stored_name)

    f.save(upload_path)

    # Record the import in the database
    db = get_db_client()
    result = db.execute(
        "INSERT INTO documents (user_id, title, file_type, mime_type, extension, file_path, file_size) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [session["user_id"], title, _file_type_for(ext), f.mimetype, ext,
         os.path.relpath(upload_path, UPLOAD_FOLDER), size],
    )

    doc_id = result.last_insert_rowid
    return jsonify({"id": doc_id, "url": url_for("import_download", doc_id=doc_id, _external=True),
                    "title": title, "file_type": _file_type_for(ext)})


@app.route("/import/list", methods=["GET"])
def list_user_documents():
    """Return a list of the current user's imported files."""
    if not session.get("user_id"):
        return jsonify({"error": "Please log in again."}), 401

    db = get_db_client()
    rows = db.execute(
        "SELECT id, title, file_type, mime_type, extension, file_path, file_size, uploaded_at "
        "FROM documents WHERE user_id = ? ORDER BY uploaded_at DESC", [session["user_id"]]
    ).rows

    return jsonify([{
        "id": r[0], "title": r[1], "file_type": r[2], "mime_type": r[3],
        "extension": r[4], "file_path": r[5], "file_size": r[6],
        "uploaded_at": r[7]
    } for r in rows])


@app.route("/import/<int:doc_id>/download")
def import_download(doc_id):
    """Return the stored file so it can be re-used in a document."""
    if not session.get("user_id"):
        return jsonify({"error": "Please log in again."}), 401

    db = get_db_client()
    rows = db.execute(
        "SELECT file_path, file_size FROM documents WHERE id = ? AND user_id = ?", [doc_id, session["user_id"]]
    ).rows
    row = rows[0] if rows else None
    if not row:
        return jsonify({"error": "File not found."}), 404

    full_path = os.path.join(UPLOAD_FOLDER, row[0])
    if not os.path.isfile(full_path):
        return jsonify({"error": "File missing on disk."}), 404

    from flask import send_file
    return send_file(full_path, as_attachment=True,
                     download_name=row[0] if False else os.path.basename(full_path))


def _file_type_for(ext):
    """Map a file extension to a human-readable file type."""
    mapping = {
        "png": "image", "jpg": "image", "jpeg": "image", "gif": "image",
        "webp": "image", "svg": "image",
        "pdf": "pdf", "doc": "document", "docx": "document", "txt": "document",
        "rtf": "document", "xls": "spreadsheet", "xlsx": "spreadsheet",
        "csv": "spreadsheet", "odp": "presentation", "ods": "presentation",
    }
    return mapping.get(ext.lower(), "document")



from lesson_routes import init_lesson_plan


def _valid_json_text(text):
    try:
        a, b = text.find("{"), text.rfind("}")
        json.loads(text[a:b + 1])
        return True
    except Exception:
        return False


def ask_ai(prompt):
    """JSON generation for lesson plans, notes, assignments and tests.
    Gemini first, then Groq. A provider that answers with broken JSON counts as a failure.
    If both fail this raises; lesson_routes then shows a clearly labelled offline template."""
    errors = []
    gemini_client = get_gemini_client()
    if gemini_client is not None:
        try:
            text = call_gemini_json(gemini_client, prompt)
            if _valid_json_text(text):
                return text
            errors.append("Gemini: reply was not valid JSON")
        except Exception as exc:
            errors.append(f"Gemini: {str(exc)[:200]}")
        print("Gemini did not produce a lesson, trying Groq:", errors[-1])

    try:
        text = call_groq_with_text(prompt, json_mode=True)
        if _valid_json_text(text):
            return text
        errors.append("Groq: reply was not valid JSON")
    except Exception as exc:
        errors.append(f"Groq: {str(exc)[:200]}")
    raise RuntimeError("AI providers unavailable. " + " | ".join(errors))


init_lesson_plan(app, ask_ai)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5001)))