import uuid
import traceback

from app import create_user, get_db_client

email = "demo@local"
password = "Password123!"
full_name = "Demo Teacher"

try:
    uid = create_user(full_name, email, password)
    print("create_user returned:", uid)

    db = get_db_client()
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

    if not uid:
        rows = db.execute("SELECT id FROM users WHERE email = ?", [email]).rows
        uid = rows[0][0] if rows else None

    conv_id = uuid.uuid4().hex
    db.execute("INSERT INTO conversations (id, user_id, title) VALUES (?, ?, ?)", [conv_id, uid, "Demo conversation"]) 
    db.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)", [conv_id, "user", "Hi, show me a demo lesson plan."])
    db.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)", [conv_id, "assistant", "Demo lesson: Topic X - Objectives: ...\nActivities: ...\nAssessment: ..."])

    print("Inserted conversation", conv_id)
except Exception:
    traceback.print_exc()
    print("Seeding failed")
