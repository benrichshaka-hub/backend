import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
from app.utils.database import get_db_connection

statements = [
    """CREATE TABLE IF NOT EXISTS lead_activities (
        id                INT AUTO_INCREMENT PRIMARY KEY,
        lead_id           INT NOT NULL,
        user_id           INT NOT NULL,
        comm_type         ENUM('call','whatsapp','email','meeting','follow_up') NOT NULL DEFAULT 'call',
        notes             TEXT NOT NULL,
        status_after      VARCHAR(50),
        next_followup_date DATE DEFAULT NULL,
        activity_date     DATE NOT NULL,
        activity_time     TIME NOT NULL,
        created_at        DATETIME DEFAULT NOW(),
        FOREIGN KEY (lead_id)  REFERENCES leads(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id)  REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS lead_status_history (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        lead_id     INT NOT NULL,
        user_id     INT NOT NULL,
        old_status  VARCHAR(50),
        new_status  VARCHAR(50) NOT NULL,
        changed_at  DATETIME DEFAULT NOW(),
        FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )"""
]

conn = get_db_connection()
cursor = conn.cursor()
for stmt in statements:
    try:
        cursor.execute(stmt)
        conn.commit()
        print(f"OK: {stmt.strip().splitlines()[0]}")
    except Exception as e:
        print(f"ERROR: {e}")
cursor.close()
conn.close()
print("Done.")
