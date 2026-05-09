from app.utils.database import get_db_connection
from datetime import datetime, date, timedelta


def _s(row):
    if not row:
        return None
    out = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif isinstance(v, timedelta):
            out[k] = str(v)
        else:
            out[k] = v
    return out


class ClientProfile:

    @staticmethod
    def create(client_id, created_by, **fields):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO client_profiles
                (client_id, address, website, instagram, facebook,
                 password, notes, status, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            client_id,
            fields.get('address'), fields.get('website'), fields.get('instagram'),
            fields.get('facebook'), fields.get('password'),
            fields.get('notes'), fields.get('status', 'active'), created_by
        ))
        conn.commit()
        profile_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO client_profile_logs (profile_id, user_id, action, detail)
            VALUES (%s, %s, 'created', %s)
        """, (profile_id, created_by, f"Profile created for {fields.get('full_name', '')}"))
        conn.commit()
        cursor.close()
        conn.close()
        return profile_id

    @staticmethod
    def get_by_client(client_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT cp.*,
                   cb.name as created_by_name,
                   ub.name as updated_by_name
            FROM client_profiles cp
            LEFT JOIN users cb ON cp.created_by = cb.id
            LEFT JOIN users ub ON cp.updated_by = ub.id
            WHERE cp.client_id = %s
            ORDER BY cp.created_at DESC
        """, (client_id,))
        rows = [_s(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return rows

    @staticmethod
    def get_by_id(profile_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT cp.*,
                   cb.name as created_by_name,
                   ub.name as updated_by_name
            FROM client_profiles cp
            LEFT JOIN users cb ON cp.created_by = cb.id
            LEFT JOIN users ub ON cp.updated_by = ub.id
            WHERE cp.id = %s
        """, (profile_id,))
        row = _s(cursor.fetchone())
        cursor.close()
        conn.close()
        return row

    @staticmethod
    def update(profile_id, updated_by, **fields):
        conn = get_db_connection()
        cursor = conn.cursor()
        allowed = ['address','website','instagram','facebook','password','notes','status']
        sets, vals = [], []
        for k in allowed:
            if k in fields:
                sets.append(f"{k}=%s")
                vals.append(fields[k])
        sets.append("updated_by=%s")
        vals.append(updated_by)
        vals.append(profile_id)
        cursor.execute(f"UPDATE client_profiles SET {', '.join(sets)} WHERE id=%s", vals)
        conn.commit()
        cursor.execute("""
            INSERT INTO client_profile_logs (profile_id, user_id, action, detail)
            VALUES (%s, %s, 'updated', %s)
        """, (profile_id, updated_by, f"Profile updated by user {updated_by}"))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def delete(profile_id, deleted_by):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO client_profile_logs (profile_id, user_id, action, detail)
            VALUES (%s, %s, 'deleted', 'Profile deleted')
        """, (profile_id, deleted_by))
        conn.commit()
        cursor.execute("DELETE FROM client_profiles WHERE id=%s", (profile_id,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def get_logs(profile_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT l.*, u.name as user_name
            FROM client_profile_logs l
            JOIN users u ON l.user_id = u.id
            WHERE l.profile_id = %s
            ORDER BY l.created_at DESC
        """, (profile_id,))
        rows = [_s(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return rows
