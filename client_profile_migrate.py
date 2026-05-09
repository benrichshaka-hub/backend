import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
from app.utils.database import get_db_connection

statements = [
    """CREATE TABLE IF NOT EXISTS client_profiles (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        client_id   INT NOT NULL,
        address     TEXT,
        website     VARCHAR(500),
        instagram   VARCHAR(500),
        facebook    VARCHAR(500),
        password    VARCHAR(500),
        notes       TEXT,
        status      ENUM('active','inactive') DEFAULT 'active',
        created_by  INT NOT NULL,
        updated_by  INT DEFAULT NULL,
        created_at  DATETIME DEFAULT NOW(),
        updated_at  DATETIME DEFAULT NOW() ON UPDATE NOW(),
        FOREIGN KEY (client_id)  REFERENCES clients(id) ON DELETE CASCADE,
        FOREIGN KEY (created_by) REFERENCES users(id),
        FOREIGN KEY (updated_by) REFERENCES users(id)
    )""",
    """CREATE TABLE IF NOT EXISTS client_profile_logs (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        profile_id  INT NOT NULL,
        user_id     INT NOT NULL,
        action      VARCHAR(50) NOT NULL,
        detail      TEXT,
        created_at  DATETIME DEFAULT NOW(),
        FOREIGN KEY (profile_id) REFERENCES client_profiles(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id)    REFERENCES users(id)
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
