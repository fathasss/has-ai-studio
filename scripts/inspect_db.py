import sqlite3
import os

def check():
    db_path = "data/traceability.db"
    # Use docker exec path if run from host for brevity in reporting
    # But usually we'll run this inside the container
    
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        print("\n--- JOB STATUS SUMMARY ---")
        c.execute("SELECT agent_name, status, COUNT(*) as count FROM llm_jobs GROUP BY agent_name, status")
        for row in c.fetchall():
            print(f"{row['agent_name']} | {row['status']} | {row['count']}")
            
        print("\n--- LATEST TRACES ---")
        c.execute("SELECT agent_name, status, timestamp FROM llm_traces ORDER BY timestamp DESC LIMIT 5")
        for row in c.fetchall():
            print(f"{row['agent_name']}: {row['status']} @ {row['timestamp']}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    check()
