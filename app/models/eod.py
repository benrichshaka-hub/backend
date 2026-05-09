from app.utils.database import get_db_connection
from datetime import date, datetime, timedelta


def _s(row):
    if not row:
        return None
    out = {}
    for k, v in row.items():
        if isinstance(v, timedelta):
            t = int(v.total_seconds())
            out[k] = f"{t // 3600:02d}:{(t % 3600) // 60:02d}"
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _build_from_worklogs(user_id, report_date, conn):
    """Auto-build EOD data from attendance + work_logs for a given user/date."""
    cursor = conn.cursor(dictionary=True)

    # Login/logout from attendance
    cursor.execute("""
        SELECT check_in_time, check_out_time
        FROM attendance WHERE user_id=%s AND date=%s
    """, (user_id, report_date))
    att = cursor.fetchone()
    login_time = ''
    logout_time = ''
    if att:
        if att['check_in_time']:
            v = att['check_in_time']
            if isinstance(v, timedelta):
                t = int(v.total_seconds()); login_time = f"{t//3600:02d}:{(t%3600)//60:02d}"
            elif isinstance(v, datetime):
                login_time = v.strftime('%H:%M')
            else:
                login_time = str(v)[:5]
        if att['check_out_time']:
            v = att['check_out_time']
            if isinstance(v, timedelta):
                t = int(v.total_seconds()); logout_time = f"{t//3600:02d}:{(t%3600)//60:02d}"
            elif isinstance(v, datetime):
                logout_time = v.strftime('%H:%M')
            else:
                logout_time = str(v)[:5]

    # Work log entries for that date
    cursor.execute("""
        SELECT wl.start_time, wl.end_time, wl.work_description,
               c.company_name, wl.client_id
        FROM work_logs wl
        LEFT JOIN clients c ON wl.client_id = c.id
        WHERE wl.user_id=%s AND wl.log_date=%s
        ORDER BY wl.start_time
    """, (user_id, report_date))
    rows = cursor.fetchall()
    cursor.close()

    entries = []
    for r in rows:
        st = r['start_time']
        et = r['end_time']
        if isinstance(st, timedelta):
            t = int(st.total_seconds()); st = f"{t//3600:02d}:{(t%3600)//60:02d}"
        elif isinstance(st, datetime):
            st = st.strftime('%H:%M')
        elif st:
            st = str(st)[:5]
        if isinstance(et, timedelta):
            t = int(et.total_seconds()); et = f"{t//3600:02d}:{(t%3600)//60:02d}"
        elif isinstance(et, datetime):
            et = et.strftime('%H:%M')
        elif et:
            et = str(et)[:5]
        entries.append({
            'start_time': st or '',
            'end_time': et or '',
            'client_id': r['client_id'],
            'company_name': r['company_name'] or '',
            'description': r['work_description'] or '',
        })

    return login_time, logout_time, entries


class EODReport:
    @staticmethod
    def get_for_user(user_id, report_date):
        """Build EOD from worklogs. If user has saved overrides, merge them."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        login_time, logout_time, entries = _build_from_worklogs(user_id, report_date, conn)

        # Check for saved overrides
        cursor.execute(
            "SELECT * FROM eod_reports WHERE user_id=%s AND report_date=%s",
            (user_id, report_date)
        )
        saved = _s(cursor.fetchone())
        if saved:
            # Use saved login/logout if user edited them
            login_time = saved.get('login_time') or login_time
            logout_time = saved.get('logout_time') or logout_time

        cursor.close()
        conn.close()
        return {
            'report_date': report_date,
            'login_time': login_time,
            'logout_time': logout_time,
            'entries': entries,
            'has_worklogs': len(entries) > 0,
        }

    @staticmethod
    def get_my_reports(user_id, start_date=None, end_date=None):
        """Get all dates that have worklogs for this user."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        q = """
            SELECT DISTINCT wl.log_date as report_date
            FROM work_logs wl
            WHERE wl.user_id=%s
        """
        params = [user_id]
        if start_date:
            q += " AND wl.log_date >= %s"; params.append(start_date)
        if end_date:
            q += " AND wl.log_date <= %s"; params.append(end_date)
        q += " ORDER BY wl.log_date DESC"
        cursor.execute(q, params)
        dates = [r['report_date'].isoformat() if hasattr(r['report_date'], 'isoformat') else r['report_date'] for r in cursor.fetchall()]
        cursor.close()
        conn.close()

        reports = []
        for d in dates:
            reports.append(EODReport.get_for_user(user_id, d))
        return reports

    @staticmethod
    def save_overrides(user_id, report_date, login_time, logout_time, organisation_id=None):
        """Save only login/logout time overrides."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO eod_reports (user_id, report_date, login_time, logout_time, organisation_id)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE login_time=%s, logout_time=%s, updated_at=NOW()
        """, (user_id, report_date, login_time, logout_time, organisation_id,
              login_time, logout_time))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def get_all_for_admin(report_date, organisation_id=None):
        """Get EOD for all users who have worklogs on a given date."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        q = """
            SELECT DISTINCT wl.user_id, u.name as user_name, u.role as user_role
            FROM work_logs wl
            JOIN users u ON wl.user_id = u.id
            WHERE wl.log_date=%s
        """
        params = [report_date]
        if organisation_id:
            q += " AND u.organisation_id=%s"; params.append(organisation_id)
        q += " ORDER BY u.name"
        cursor.execute(q, params)
        users = cursor.fetchall()
        cursor.close()
        conn.close()

        reports = []
        for u in users:
            data = EODReport.get_for_user(u['user_id'], report_date)
            data['user_name'] = u['user_name']
            data['user_role'] = u['user_role']
            reports.append(data)
        return reports
