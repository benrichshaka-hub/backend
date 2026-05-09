from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.models.eod import EODReport
from datetime import datetime
from zoneinfo import ZoneInfo

eod_bp = Blueprint('eod', __name__)
ADMIN_ROLES = ['admin', 'team_lead', 'crm_head', 'marketing_head']
IST = ZoneInfo('Asia/Kolkata')

def today_ist():
    return datetime.now(IST).strftime('%Y-%m-%d')


@eod_bp.route('/eod/debug', methods=['GET'])
@jwt_required()
def debug_eod():
    from app.utils.database import get_db_connection
    user_id = int(get_jwt_identity())
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, log_date, work_date, start_time, end_time, work_description FROM work_logs WHERE user_id=%s ORDER BY log_date DESC LIMIT 10", (user_id,))
    logs = cursor.fetchall()
    cursor.execute("SELECT date, check_in_time, check_out_time FROM attendance WHERE user_id=%s ORDER BY date DESC LIMIT 5", (user_id,))
    att = cursor.fetchall()
    cursor.close(); conn.close()
    from datetime import date, datetime, timedelta
    def s(v):
        if isinstance(v, (date, datetime)): return v.isoformat()
        if isinstance(v, timedelta): return str(v)
        return v
    return jsonify({
        'today_ist': today_ist(),
        'worklogs': [{k: s(vv) for k, vv in r.items()} for r in logs],
        'attendance': [{k: s(vv) for k, vv in r.items()} for r in att]
    }), 200


@eod_bp.route('/eod/my', methods=['GET'])
@jwt_required()
def get_my_eod():
    user_id = int(get_jwt_identity())
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    reports = EODReport.get_my_reports(user_id, start, end)
    return jsonify(reports), 200


@eod_bp.route('/eod/date', methods=['GET'])
@jwt_required()
def get_eod_by_date():
    user_id = int(get_jwt_identity())
    report_date = request.args.get('date', today_ist())
    report = EODReport.get_for_user(user_id, report_date)
    # debug info
    from app.utils.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT log_date FROM work_logs WHERE user_id=%s ORDER BY log_date DESC LIMIT 5", (user_id,))
    wl_dates = [str(r['log_date']) for r in cursor.fetchall()]
    cursor.close(); conn.close()
    report['_debug'] = {'queried_date': report_date, 'today_ist': today_ist(), 'recent_log_dates': wl_dates}
    return jsonify(report), 200


@eod_bp.route('/eod/edit', methods=['POST'])
@jwt_required()
def edit_eod():
    user_id = int(get_jwt_identity())
    claims = get_jwt()
    data = request.json or {}
    report_date = data.get('report_date')
    login_time = data.get('login_time')
    logout_time = data.get('logout_time')
    if not report_date or not login_time or not logout_time:
        return jsonify({'error': 'report_date, login_time, logout_time required'}), 400
    EODReport.save_overrides(
        user_id, report_date, login_time, logout_time,
        organisation_id=claims.get('organisation_id')
    )
    return jsonify({'message': 'EOD updated'}), 200


@eod_bp.route('/eod/admin', methods=['GET'])
@jwt_required()
def get_admin_eod():
    claims = get_jwt()
    if claims['role'] not in ADMIN_ROLES:
        return jsonify({'error': 'Unauthorized'}), 403
    report_date = request.args.get('date', today_ist())
    org_id = claims.get('organisation_id')
    reports = EODReport.get_all_for_admin(report_date, organisation_id=org_id)
    return jsonify(reports), 200
