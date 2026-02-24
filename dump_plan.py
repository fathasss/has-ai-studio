import sqlite3
import json
import os

db_path = 'data/traceability.db'
if not os.path.exists(db_path):
    print(f"Error: {db_path} not found")
    exit(1)

conn = sqlite3.connect(db_path)
r = conn.execute('SELECT response FROM llm_traces WHERE agent_name="TeamLead" ORDER BY timestamp DESC LIMIT 1').fetchone()
if r:
    print(r[0])
else:
    print("No TeamLead trace found")
