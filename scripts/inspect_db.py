import sqlite3
import json
import os

def check():
    db_path = "data/traceability.db"
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        print("--- LATEST TRACES ---")
        c.execute("SELECT agent_name, status, timestamp FROM llm_traces ORDER BY timestamp DESC LIMIT 10")
        for row in c.fetchall():
            print(f"{row['agent_name']}: {row['status']} @ {row['timestamp']}")
            
        print("\n--- JOB STATUS SUMMARY ---")
        c.execute("SELECT agent_name, status, COUNT(*) as count FROM llm_jobs GROUP BY agent_name, status")
        for row in c.fetchall():
            print(f"{row['agent_name']} | {row['status']} | {row['count']}")
            
        print("\n--- PENDING/PROCESSING JOBS ---")
        c.execute("SELECT id, agent_name, status, sprint_id FROM llm_jobs WHERE status != 'COMPLETED'")
        for row in c.fetchall():
            print(f"ID: {row['id']} | Agent: {row['agent_name']} | Status: {row['status']} | Sprint: {row['sprint_id']}")
            
        print("\n--- LATEST TEAMLEAD PLAN ---")
        c.execute("SELECT sprint_id, response FROM llm_traces WHERE agent_name='TeamLead' ORDER BY timestamp DESC LIMIT 1")
        row = c.fetchone()
        if row:
            print(f"Sprint: {row['sprint_id']}")
            print(row['response'])
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    check()
