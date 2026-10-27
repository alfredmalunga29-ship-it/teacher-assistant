r"""Quick database check. Run from the project folder:
    .\.venv312\Scripts\python.exe check_db.py
It prints what is wrong (network, address, or password/token) without showing your secrets."""
import os
import socket
import time
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
url = os.getenv("TURSO_DATABASE_URL") or ""
token = os.getenv("TURSO_AUTH_TOKEN") or ""

print("TURSO_DATABASE_URL set:", bool(url), "| TURSO_AUTH_TOKEN set:", bool(token))
if not url or not token:
    raise SystemExit("Add TURSO_DATABASE_URL and TURSO_AUTH_TOKEN to .env first.")

host = urlparse(url.replace("libsql://", "https://")).hostname
print("Database host:", host)
try:
    print("Internet/DNS lookup OK ->", socket.gethostbyname(host))
except Exception as exc:
    raise SystemExit(f"Cannot find the database address ({exc}). Check your internet, or the URL in .env.")

import libsql_client

for attempt in range(1, 4):
    try:
        with libsql_client.create_client_sync(url=url.replace("libsql://", "https://"), auth_token=token) as client:
            rows = client.execute("SELECT 1").rows
        print(f"Attempt {attempt}: connected OK, SELECT 1 ->", rows[0][0])
        break
    except Exception as exc:
        print(f"Attempt {attempt}: {type(exc).__name__}: {str(exc)[:200]}")
        time.sleep(1)
else:
    print("\nAll 3 attempts failed. See the notes in the chat for what each message means.")
