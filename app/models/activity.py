from app.utils.database import get_db_connection
from app.utils.timezone import now_ist, today_ist
from datetime import datetime, date, timedelta
from decimal import Decimal


def _s(row):
    if row is None:
        return None
    out = {}
    for k, v in row.items():
        if isinstance(v, timedelta):
            total = int(v.total_seconds())
            out[k] = f"{total // 3600:02d}:{(total % 3600) // 60:02d}"
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


class ActivityLog:

    @staticmethod
    def heartbeat(user_id: int, status: str, idle_seconds: int, events: list):
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        now    = now_ist()
        INTERVAL     = 30
        active_delta = 0 if status == 'idle' else INTERVAL
        idle_delta   = INTERVAL if status == 'idle' else 0
        cursor.execute(
            "SELECT last_heartbeat, today_active_seconds, today_idle_seconds "
            "FROM employee_status WHERE user_id = %s", (user_id,)
        )
        row = cursor.fetchone()
        if row and row['last_heartbeat']:
            last = row['last_heartbeat']
            if isinstance(last, str):
                last = datetime.fromisoformat(last)
            if last.date() < today_ist():
                active_delta = 0
                idle_delta   = 0
        prev_active = (row['today_active_seconds'] or 0) if row else 0
        prev_idle   = (row['today_idle_seconds']   or 0) if row else 0
        new_active  = prev_active + active_delta
        new_idle    = prev_idle   + idle_delta
        total       = new_active + new_idle
        score       = round((new_active / total) * 100, 2) if total > 0 else 0
        cursor.execute("""
            INSERT INTO employee_status
                (user_id, status, last_active, last_heartbeat,
                 today_active_seconds, today_idle_seconds, productivity_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status                = VALUES(status),
                last_active           = IF(VALUES(status) != 'idle', VALUES(last_active), last_active),
                last_heartbeat        = VALUES(last_heartbeat),
                today_active_seconds  = IF(DATE(last_heartbeat) < CURDATE(), VALUES(today_active_seconds),
                                           today_active_seconds + %s),
                today_idle_seconds    = IF(DATE(last_heartbeat) < CURDATE(), VALUES(today_idle_seconds),
                                           today_idle_seconds + %s),
                productivity_score    = VALUES(productivity_score)
        """, (user_id, status, now, now, new_active, new_idle, score, active_delta, idle_delta))
        if events:
            events = events[:100]
            cursor.executemany("""
                INSERT INTO activity_logs (user_id, timestamp, activity_type, duration_seconds)
                VALUES (%s, %s, %s, %s)
            """, [
                (user_id,
                 datetime.fromtimestamp(e.get('ts', now.timestamp()) / 1000),
                 e.get('type', 'active'),
                 e.get('duration', 0))
                for e in events
            ])
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def set_offline(user_id: int):
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE employee_status SET status='offline' WHERE user_id=%s", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def get_live_all(organisation_id=None):
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        org_f  = "AND u.organisation_id = %s" if organisation_id is not None else ""
        params = ([organisation_id] if organisation_id is not None else [])
        cursor.execute(f"""
            SELECT
                u.id, u.name, u.role, u.profile_image,
                t.name  AS team_name,
                dp.name AS department_name,
                COALESCE(es.status, 'offline') AS status,
                es.last_active,
                es.last_heartbeat,
                es.today_active_seconds,
                es.today_idle_seconds,
                es.productivity_score,
                a.check_in_time,
                a.check_out_time
            FROM users u
            LEFT JOIN employee_status es ON u.id = es.user_id
            LEFT JOIN teams t ON u.team_id = t.id
            LEFT JOIN departments dp ON u.department_id = dp.id
            LEFT JOIN attendance a ON u.id = a.user_id AND a.date = CURDATE()
            WHERE u.role NOT IN ('admin', 'client') {org_f}
            ORDER BY FIELD(COALESCE(es.status,'offline'), 'active','online','idle','away','offline'), u.name
        """, params)
        rows = [_s(r) for r in cursor.fetchall()]
        
        from app.routes.auth import PROFILE_UPLOAD_FOLDER
        import os
        for r in rows:
            if r.get('profile_image'):
                try:
                    path = os.path.join(PROFILE_UPLOAD_FOLDER, r['profile_image'])
                    if os.path.exists(path):
                        r['profile_image'] = f"{r['profile_image']}?t={int(os.path.getmtime(path))}"
                except: pass

        cursor.close()
        conn.close()
        cutoff = now_ist() - timedelta(minutes=2)
        for r in rows:
            if r['last_heartbeat']:
                lh = datetime.fromisoformat(r['last_heartbeat']) if isinstance(r['last_heartbeat'], str) else r['last_heartbeat']
                if lh < cutoff and r['status'] not in ('offline',):
                    r['status'] = 'away'
        return rows

    @staticmethod
    def get_summary(user_id: int, target_date: str = None):
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        d = target_date or today_ist().isoformat()
        cursor.execute("""
            SELECT activity_type, COUNT(*) AS events, SUM(duration_seconds) AS total_seconds
            FROM activity_logs
            WHERE user_id = %s AND DATE(timestamp) = %s
            GROUP BY activity_type
        """, (user_id, d))
        breakdown = [_s(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM employee_status WHERE user_id = %s", (user_id,))
        live = _s(cursor.fetchone())
        cursor.close()
        conn.close()
        return {'breakdown': breakdown, 'live': live}

    @staticmethod
    def get_productivity_report(start_date: str, end_date: str, user_id: int = None):
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query  = """
            SELECT
                u.id AS user_id, u.name, u.role,
                t.name AS team_name,
                DATE(al.timestamp) AS log_date,
                SUM(CASE WHEN al.activity_type IN ('active','mouse','keyboard')
                         THEN al.duration_seconds ELSE 0 END) AS active_seconds,
                SUM(CASE WHEN al.activity_type = 'idle'
                         THEN al.duration_seconds ELSE 0 END) AS idle_seconds,
                COUNT(*) AS total_events
            FROM activity_logs al
            JOIN users u ON al.user_id = u.id
            LEFT JOIN teams t ON u.team_id = t.id
            WHERE DATE(al.timestamp) BETWEEN %s AND %s
        """
        params = [start_date, end_date]
        if user_id:
            query += " AND al.user_id = %s"
            params.append(user_id)
        query += " GROUP BY u.id, DATE(al.timestamp) ORDER BY log_date DESC, u.name"
        cursor.execute(query, params)
        rows = [_s(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return rows
