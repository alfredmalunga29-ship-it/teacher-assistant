from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
import os
import re
import socket
import hashlib
import binascii
import traceback
import libsql_client
from dotenv import load_dotenv
from google import genai
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from curriculum import CURRICULA, DURATIONS, SUBJECTS, TOPICS
from lesson_docx import schema

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# A blunt but effective safety net: without this, a database or network hiccup could
# hang a request indefinitely with no error at all. 10 seconds is generous enough for
# a slow connection, but short enough that a user isn't stuck waiting forever.
socket.setdefaulttimeout(10)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")


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

# Prefer the known-good Gemini alias for the current google-genai SDK.
# Older app versions used a retired alias, which caused the fallback path to trigger.
MODEL_NAME = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=2))
def call_gemini_with_retry(client, user_message):
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=f"{SYSTEM_INSTRUCTION}\n\nTeacher's request: {user_message}",
    )
    if hasattr(response, "text") and response.text:
        return response.text
    if isinstance(response, dict):
        return response.get("text") or json.dumps(response)
    return str(response)


def _groq_model_candidates():
    preferred = os.getenv("GROQ_MODEL")
    candidates = []
    for name in [preferred, "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]:
        if name and name not in candidates:
            candidates.append(name)
    return candidates


def call_groq_with_text(prompt):
    client = get_groq_client()
    if client is None:
        raise RuntimeError("Groq is not configured")

    last_exc = None
    for model in _groq_model_candidates():
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as exc:
            last_exc = exc
            message = str(exc).lower()
            if "404" in message or "not found" in message or "model" in message:
                print(f"Groq model {model!r} unavailable, trying fallback: {exc}")
                continue
            raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("No Groq model was available")


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


def generate_ai_reply(user_message):
    gemini_client = get_gemini_client()
    if gemini_client is not None:
        try:
            return call_gemini_with_retry(gemini_client, user_message)
        except Exception as exc:
            traceback.print_exc()
            print("Gemini failure, trying Groq fallback:", repr(exc))

    try:
        return call_groq_with_text(f"{SYSTEM_INSTRUCTION}\n\nTeacher's request: {user_message}")
    except Exception as exc:
        traceback.print_exc()
        print("AI providers unavailable, using offline demo chat response:", repr(exc))
        return _offline_chat_reply(user_message)


# ---------- Database (Turso) ----------
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")


def get_db_client():
    if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
        raise RuntimeError(
            "Missing Turso configuration. Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN "
            "in the environment before using the database."
        )
    connect_url = TURSO_DATABASE_URL.replace("libsql://", "https://")
    return libsql_client.create_client_sync(url=connect_url, auth_token=TURSO_AUTH_TOKEN)


def init_db():
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
    if "chat_history" not in session:
        session["chat_history"] = []
    cfg = {"curricula": CURRICULA, "subjects": SUBJECTS, "durations": DURATIONS, "topics": TOPICS, "schema": schema()}
    return render_template("chat.html", messages=session["chat_history"], full_name=session.get("full_name", ""), cfg=cfg)


@app.route("/send", methods=["POST"])
def send():
    if not session.get("user_id"):
        return jsonify({"error": "Please log in again."}), 401

    user_message = request.json.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    if "chat_history" not in session:
        session["chat_history"] = []

    session["chat_history"].append({"role": "user", "content": user_message})

    try:
        reply = generate_ai_reply(user_message)
    except Exception as e:
        message = str(e).lower()
        if "resource_exhausted" in message or "quota" in message or "429" in message or "groq" in message:
            reply = "The AI service is currently unavailable. Please try again in a moment."
        else:
            reply = f"Sorry, something went wrong: {e}"

    session["chat_history"].append({"role": "assistant", "content": reply})
    session.modified = True

    return jsonify({"reply": reply})


@app.route("/clear", methods=["POST"])
def clear():
    if not session.get("user_id"):
        return jsonify({"error": "Please log in again."}), 401
    session["chat_history"] = []
    return jsonify({"status": "cleared"})


from lesson_routes import init_lesson_plan


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=2), reraise=True)
def ask_ai(prompt):
    # Try Gemini first; if it is quota-blocked or fails for any other reason,
    # fall back to Groq for the lesson-plan JSON generation.
    gemini_client = get_gemini_client()
    if gemini_client is not None:
        try:
            return call_gemini_with_retry(gemini_client, prompt)
        except Exception as exc:
            traceback.print_exc()
            print("Gemini failure, falling back to Groq for lesson generation:", repr(exc))

    try:
        return call_groq_with_text(prompt)
    except Exception as exc:
        traceback.print_exc()
        print("AI providers unavailable, using offline prompt-aware fallback:", repr(exc))
        return _offline_fallback_json_from_prompt(prompt)


init_lesson_plan(app, ask_ai)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5001)))
