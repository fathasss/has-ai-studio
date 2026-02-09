import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "tasks.db")

def get_conn():
    os.makedirs(DATA_DIR, exist_ok=True)  # 🔥 kritik satır
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            task TEXT,
            result TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()

def save_task(role, task, result):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO tasks (role, task, result, created_at) VALUES (?, ?, ?, datetime('now'))",
        (role, task, result)
    )

    conn.commit()
    conn.close()

def get_tasks():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT role, task, result, created_at FROM tasks ORDER BY id DESC")
    rows = cur.fetchall()

    conn.close()
    return rows
