import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()
from app.utils.database import get_db_connection

statements = [
    """CREATE TABLE IF NOT EXISTS eod_reports (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        user_id         INT NOT NULL,
        report_date     DATE NOT NULL,
        login_time      VARCHAR(10) NOT NULL,
        logout_time     VARCHAR(10) NOT NULL,
        organisation_id INT DEFAULT NULL,
        created_at      DATETIME DEFAULT NOW(),
        updated_at      DATETIME DEFAULT NOW() ON UPDATE NOW(),
        UNIQUE KEY uq_user_date (user_id, report_date),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS eod_entries (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        report_id   INT NOT NULL,
        start_time  VARCHAR(10),
        end_time    VARCHAR(10),
        client_id   INT DEFAULT NULL,
        description TEXT NOT NULL,
        FOREIGN KEY (report_id) REFERENCES eod_reports(id) ON DELETE CASCADE,
        FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL
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
