import sqlite3
import json

def check_trace():
    conn = sqlite3.connect('data/traceability.db')
    cursor = conn.cursor()
    cursor.execute('SELECT response FROM llm_traces WHERE prompt="Generated from UI Preview" ORDER BY timestamp DESC LIMIT 1')
    row = cursor.fetchone()
    if row:
        print(row[0])
    else:
        print("No trace found")
    conn.close()

if __name__ == "__main__":
    check_trace()
