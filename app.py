from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
import socket
import hashlib
import binascii
import libsql_client
from dotenv import load_dotenv
from google import genai

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

SYSTEM_INSTRUCTION = (
    "You are a helpful assistant for teachers. You help create lesson plans, "
    "quizzes, grading rubrics, and report card comments. Be practical and concise."
)

# "gemini-2.5-flash" is a floating alias Google keeps pointed at their current
# recommended fast model — this avoids hard-coding a specific dated model name
# that could get deprecated later (exactly what happened with Groq's playai-tts).
MODEL_NAME = "gemini-2.5-flash"


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
    return render_template("chat.html", messages=session["chat_history"], full_name=session.get("full_name", ""))


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

    gemini_client = get_gemini_client()
    if gemini_client is None:
        return jsonify({"error": "Gemini is not configured. Set GEMINI_API_KEY in the environment before sending a message."}), 503

    try:
        chat = gemini_client.chats.create(model=MODEL_NAME)
        response = chat.send_message(f"{SYSTEM_INSTRUCTION}\n\nTeacher's request: {user_message}")
        reply = response.text
    except Exception as e:
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


if __name__ == "__main__":
    app.run(debug=True, port=5001)