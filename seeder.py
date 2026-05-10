"""
seeder.py — Insert teams, departments, and all employees into the database.
Run from the backend folder:  python seeder.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from werkzeug.security import generate_password_hash
from app.utils.database import get_db_connection


def hash_password(password: str) -> str:
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)


# ── Organisation Structure ────────────────────────────────────
#
#  Team 1: Marketing
#    (no departments — Prabhakaran is the head)
#
#  Team 2: CRM
#    Dept 1: Development    — Head: Albin
#    Dept 2: Video Editing  — Head: Ahmed Bathusha
#    Dept 3: SMM            — Head: Chitra Ananth
#    Dept 4: Design         — Head: Gangatharan K
#
# ─────────────────────────────────────────────────────────────

TEAMS = [
    "Marketing",
    "CRM",
]

# (dept_name, team_name)
DEPARTMENTS = [
    ("Development",   "CRM"),
    ("Video Editing", "CRM"),
    ("SMM",           "CRM"),
    ("Design",        "CRM"),
]

# (name, email, password, role, team_name, dept_name)
EMPLOYEES = [
    # Main Admin
    ("Admin",             "admin@kaira.com",       "admin123",       "admin",          None,          None),

    # Marketing team head
    ("Prabhakaran B",     "prabhakaran@gmail.com", "prabhakaran123", "marketing_head", "Marketing",   None),

    # CRM team head
    ("Vidhya A",          "vidhya@gmail.com",       "vidhya123",      "crm",            "CRM",         None),

    # Development dept
    ("Albin",             "albin@gmail.com",         "albin123",       "team_lead",      "CRM",         "Development"),
    ("Arun Kumar",        "arun@gmail.com",           "arun123",        "developer",      "CRM",         "Development"),
    ("Aswin",             "aswin@gmail.com",          "aswin123",       "developer",      "CRM",         "Development"),
    ("Pradheeba",         "pradheeba@gmail.com",      "pradheeba123",   "developer",      "CRM",         "Development"),
    ("Sweetline",         "sweet@gmail.com",          "sweet123",       "developer",      "CRM",         "Development"),

    # Video Editing dept
    ("Ahmed Bathusha",    "ahmed@gmail.com",          "ahmed123",       "team_lead",      "CRM",         "Video Editing"),

    # SMM dept
    ("Chitra Ananth",     "ananth@gmail.com",         "ananth123",      "smm",            "CRM",         "SMM"),
    ("Naga Meena S",      "meena@gmail.com",          "meena123",       "employee",       "CRM",         "SMM"),

    # Design dept
    ("Gangatharan K",     "gangatharan@gmail.com",    "gangatharan123", "team_lead",      "CRM",         "Design"),
    ("Aswin Boopathy S",  "boopathy@gmail.com",       "boopathy123",    "employee",       "CRM",         "Design"),
    ("Nikhil",            "nikhil@gmail.com",         "Nikil123",       "employee",       "CRM",         "Design"),
    ("Vanniya Perumal E", "perumal@gmail.com",        "perumal123",     "employee",       "CRM",         "Design"),
]


def seed():
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # ── 1. Insert Teams ───────────────────────────────────────
    print("\n── Teams ──")
    team_ids = {}
    for team_name in TEAMS:
        cursor.execute("SELECT id FROM teams WHERE name = %s", (team_name,))
        row = cursor.fetchone()
        if row:
            team_ids[team_name] = row['id']
            print(f"  SKIP   Team: {team_name} (exists)")
        else:
            cursor.execute("INSERT INTO teams (name) VALUES (%s)", (team_name,))
            conn.commit()
            team_ids[team_name] = cursor.lastrowid
            print(f"  INSERT Team: {team_name} (id={cursor.lastrowid})")

    # ── 2. Insert Departments ─────────────────────────────────
    print("\n── Departments ──")
    dept_ids = {}
    for dept_name, team_name in DEPARTMENTS:
        team_id = team_ids[team_name]
        cursor.execute("SELECT id FROM departments WHERE name = %s AND team_id = %s", (dept_name, team_id))
        row = cursor.fetchone()
        if row:
            dept_ids[dept_name] = row['id']
            print(f"  SKIP   Dept: {dept_name} under {team_name} (exists)")
        else:
            cursor.execute("INSERT INTO departments (name, team_id) VALUES (%s, %s)", (dept_name, team_id))
            conn.commit()
            dept_ids[dept_name] = cursor.lastrowid
            print(f"  INSERT Dept: {dept_name} under {team_name} (id={cursor.lastrowid})")

    # ── 3. Insert Employees ───────────────────────────────────
    print("\n── Employees ──")
    inserted = 0
    skipped  = 0

    for name, email, password, role, team_name, dept_name in EMPLOYEES:
        cursor.execute("SELECT id FROM users WHERE email = %s", (email.lower(),))
        if cursor.fetchone():
            print(f"  SKIP   {email} (already exists)")
            skipped += 1
            continue

        team_id = team_ids.get(team_name)
        dept_id = dept_ids.get(dept_name) if dept_name else None
        hashed  = hash_password(password)

        cursor.execute("""
            INSERT INTO users (name, email, password, role, team_id, department_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (name, email.lower(), hashed, role, team_id, dept_id))
        conn.commit()
        print(f"  INSERT {name} ({role}) → Team: {team_name}, Dept: {dept_name or '-'}")
        inserted += 1

    cursor.close()
    conn.close()

    print(f"\n✓ Done. {inserted} employees inserted, {skipped} skipped.")
    print("  Teams created:", list(team_ids.keys()))
    print("  Departments created:", list(dept_ids.keys()))


if __name__ == "__main__":
    if '--superadmin' in sys.argv:
        # ── Create first superadmin ───────────────────────────
        print("\n── Creating SuperAdmin ──")
        name     = input("SuperAdmin Name: ").strip()
        email    = input("SuperAdmin Email: ").strip().lower()
        password = input("SuperAdmin Password: ").strip()

        if not name or not email or not password:
            print("ERROR: All fields are required.")
            sys.exit(1)

        from app.models.superadmin import SuperAdmin
        existing = SuperAdmin.get_by_email(email)
        if existing:
            print(f"ERROR: SuperAdmin with email '{email}' already exists.")
            sys.exit(1)

        sa_id = SuperAdmin.create(name=name, email=email, password=password)
        print(f"\n✓ SuperAdmin created successfully!")
        print(f"  ID:    {sa_id}")
        print(f"  Name:  {name}")
        print(f"  Email: {email}")
        print(f"\n  Login at: POST /api/superadmin/login")
    else:
        seed()
