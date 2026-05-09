from app.utils.database import get_db_connection

def update_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Update announcements table
    print("Updating announcements table...")
    try:
        cursor.execute("ALTER TABLE announcements ADD COLUMN is_pinned TINYINT DEFAULT 0")
    except: print("is_pinned already exists")
    
    try:
        cursor.execute("ALTER TABLE announcements ADD COLUMN views INT DEFAULT 0")
    except: print("views already exists")
    
    try:
        cursor.execute("ALTER TABLE announcements ADD COLUMN poll_data JSON DEFAULT NULL")
    except: print("poll_data already exists")

    # 2. Create announcement_likes table
    print("Creating announcement_likes table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcement_likes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            announcement_id INT NOT NULL,
            user_id INT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY (announcement_id, user_id),
            FOREIGN KEY (announcement_id) REFERENCES announcements(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("DB Update Complete.")

if __name__ == "__main__":
    update_db()
