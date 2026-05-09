from app.utils.database import get_db_connection
import sys

def check_user(uid):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, name, email, profile_image FROM users WHERE id = %s", (uid,))
        user = cursor.fetchone()
        print(user)
    finally:
        conn.close()

if __name__ == "__main__":
    uid = sys.argv[1] if len(sys.argv) > 1 else 27
    check_user(uid)
