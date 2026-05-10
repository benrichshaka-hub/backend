"""
Run once: adds profile_image_data column to users table.
  python migrate_profile_image_db.py
"""
from app.utils.database import get_db_connection

conn = get_db_connection()
cursor = conn.cursor()
try:
    cursor.execute("""
        ALTER TABLE users
        ADD COLUMN profile_image_data MEDIUMTEXT NULL DEFAULT NULL
    """)
    conn.commit()
    print("Migration successful: profile_image_data column added.")
except Exception as e:
    if 'Duplicate column' in str(e):
        print("Column already exists, skipping.")
    else:
        raise
finally:
    cursor.close()
    conn.close()
