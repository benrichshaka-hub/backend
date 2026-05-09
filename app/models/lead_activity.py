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


class LeadActivity:

    @staticmethod
    def add(lead_id, user_id, comm_type, notes, status_after,
            next_followup_date, activity_date, activity_time):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO lead_activities
                (lead_id, user_id, comm_type, notes, status_after,
                 next_followup_date, activity_date, activity_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (lead_id, user_id, comm_type, notes, status_after,
              next_followup_date or None, activity_date, activity_time))
        conn.commit()
        act_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return act_id

    @staticmethod
    def get_by_lead(lead_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT a.*, u.name as user_name
            FROM lead_activities a
            JOIN users u ON a.user_id = u.id
            WHERE a.lead_id = %s
            ORDER BY a.activity_date DESC, a.activity_time DESC
        """, (lead_id,))
        rows = [_s(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return rows

    @staticmethod
    def delete(activity_id):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM lead_activities WHERE id=%s", (activity_id,))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def add_status_history(lead_id, user_id, old_status, new_status):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO lead_status_history (lead_id, user_id, old_status, new_status)
            VALUES (%s,%s,%s,%s)
        """, (lead_id, user_id, old_status, new_status))
        conn.commit()
        cursor.close()
        conn.close()

    @staticmethod
    def get_status_history(lead_id):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT h.*, u.name as user_name
            FROM lead_status_history h
            JOIN users u ON h.user_id = u.id
            WHERE h.lead_id = %s
            ORDER BY h.changed_at ASC
        """, (lead_id,))
        rows = [_s(r) for r in cursor.fetchall()]
        cursor.close()
        conn.close()
        return rows

    @staticmethod
    def get_analytics(organisation_id=None):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        today = date.today().isoformat()

        org_join  = "JOIN users u2 ON l.assigned_to = u2.id" if organisation_id else ""
        org_where = "AND u2.organisation_id = %s" if organisation_id else ""
        params_org = [organisation_id] if organisation_id else []

        # Total activities per comm type
        cursor.execute(f"""
            SELECT a.comm_type, COUNT(*) as total
            FROM lead_activities a
            JOIN leads l ON a.lead_id = l.id
            {org_join}
            WHERE 1=1 {org_where}
            GROUP BY a.comm_type
        """, params_org)
        by_type = {r['comm_type']: r['total'] for r in cursor.fetchall()}

        # Pending follow-ups (next_followup_date >= today)
        cursor.execute(f"""
            SELECT COUNT(*) as cnt
            FROM lead_activities a
            JOIN leads l ON a.lead_id = l.id
            {org_join}
            WHERE a.next_followup_date >= %s
            AND l.status NOT IN ('converted','lost') {org_where}
        """, [today] + params_org)
        pending = cursor.fetchone()['cnt']

        # Overdue follow-ups (next_followup_date < today)
        cursor.execute(f"""
            SELECT COUNT(*) as cnt
            FROM lead_activities a
            JOIN leads l ON a.lead_id = l.id
            {org_join}
            WHERE a.next_followup_date < %s
            AND l.status NOT IN ('converted','lost') {org_where}
        """, [today] + params_org)
        overdue = cursor.fetchone()['cnt']

        # Team performance
        cursor.execute(f"""
            SELECT u.name as user_name, u.role,
                   COUNT(a.id) as total_activities,
                   COUNT(DISTINCT a.lead_id) as leads_handled
            FROM lead_activities a
            JOIN users u ON a.user_id = u.id
            JOIN leads l ON a.lead_id = l.id
            {org_join.replace('u2','u3') if org_join else ''}
            WHERE 1=1 {org_where.replace('u2','u3') if org_where else ''}
            GROUP BY u.id
            ORDER BY total_activities DESC
        """, params_org)
        team = [_s(r) for r in cursor.fetchall()]

        # Overdue list
        cursor.execute(f"""
            SELECT a.*, l.name as lead_name, l.company, u.name as user_name
            FROM lead_activities a
            JOIN leads l ON a.lead_id = l.id
            JOIN users u ON a.user_id = u.id
            {org_join}
            WHERE a.next_followup_date < %s
            AND l.status NOT IN ('converted','lost') {org_where}
            ORDER BY a.next_followup_date ASC
            LIMIT 20
        """, [today] + params_org)
        overdue_list = [_s(r) for r in cursor.fetchall()]

        # Upcoming follow-ups (next 7 days)
        from datetime import timedelta
        next7 = (date.today() + timedelta(days=7)).isoformat()
        cursor.execute(f"""
            SELECT a.*, l.name as lead_name, l.company, u.name as user_name
            FROM lead_activities a
            JOIN leads l ON a.lead_id = l.id
            JOIN users u ON a.user_id = u.id
            {org_join}
            WHERE a.next_followup_date BETWEEN %s AND %s
            AND l.status NOT IN ('converted','lost') {org_where}
            ORDER BY a.next_followup_date ASC
            LIMIT 20
        """, [today, next7] + params_org)
        upcoming = [_s(r) for r in cursor.fetchall()]

        cursor.close()
        conn.close()
        return {
            'by_type': by_type,
            'pending_followups': pending,
            'overdue_followups': overdue,
            'team_performance': team,
            'overdue_list': overdue_list,
            'upcoming_followups': upcoming,
        }
