from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.models.other import WorkLog, Notification, File, CompanySettings
from werkzeug.utils import secure_filename
import os

other_bp = Blueprint('other', __name__)

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

LEAD_ROLES = ['admin', 'team_lead', 'crm_head', 'marketing_head']


@other_bp.route('/worklogs', methods=['POST'])
@other_bp.route('/worklogs/submit', methods=['POST'])
@jwt_required()
def create_worklog():
    data = request.json
    user_id = int(get_jwt_identity())
    try:
        log_id = WorkLog.create(
            user_id=user_id,
            client_id=int(data['client_id']) if data.get('client_id') else None,
            lead_id=int(data['lead_id']) if data.get('lead_id') else None,
            task_id=int(data['task_id']) if data.get('task_id') else None,
            work_description=data['work_description'],
            hours_worked=data['hours_worked'],
            log_date=data['log_date'],
            start_time=data.get('start_time') or None,
            end_time=data.get('end_time') or None,
            department=data.get('department') or None,
            team_leader_id=int(data['team_leader_id']) if data.get('team_leader_id') else None,
            duration_minutes=int(data['duration_minutes']) if data.get('duration_minutes') else None,
            work_date=data.get('work_date') or data.get('log_date'),
            status=data.get('status', 'completed')
        )
        return jsonify({"message": "Work log created", "log_id": log_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@other_bp.route('/worklogs', methods=['GET'])
@jwt_required()
def get_worklogs():
    user_id    = int(get_jwt_identity())
    claims     = get_jwt()
    org_id     = claims.get('organisation_id')
    client_id  = request.args.get('client_id')
    start_date = request.args.get('start_date')
    end_date   = request.args.get('end_date')
    department = request.args.get('department')
    emp_id     = request.args.get('user_id')

    if claims['role'] in LEAD_ROLES and not client_id:
        logs = WorkLog.get_all_for_admin(
            start_date, end_date,
            client_id=int(client_id) if client_id else None,
            department=department,
            user_id=int(emp_id) if emp_id else None,
            organisation_id=org_id
        )
    elif client_id:
        logs = WorkLog.get_by_client(int(client_id), start_date, end_date)
    else:
        logs = WorkLog.get_by_user(user_id, start_date, end_date)

    return jsonify(logs), 200


@other_bp.route('/worklogs/team', methods=['GET'])
@jwt_required()
def get_team_worklogs():
    user_id = int(get_jwt_identity())
    claims = get_jwt()
    if claims['role'] not in LEAD_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    logs = WorkLog.get_by_team(
        team_leader_id=user_id,
        start_date=request.args.get('start_date'),
        end_date=request.args.get('end_date'),
        employee_id=request.args.get('employee_id'),
        client_id=request.args.get('client_id'),
        status=request.args.get('status')
    )
    return jsonify(logs), 200


@other_bp.route('/worklogs/<int:log_id>/approve', methods=['PATCH'])
@jwt_required()
def approve_worklog(log_id):
    user_id = int(get_jwt_identity())
    claims = get_jwt()
    if claims['role'] not in LEAD_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    WorkLog.approve(log_id, user_id)
    return jsonify({"message": "Approved"}), 200


@other_bp.route('/worklogs/<int:log_id>/reject', methods=['PATCH'])
@jwt_required()
def reject_worklog(log_id):
    user_id = int(get_jwt_identity())
    claims = get_jwt()
    if claims['role'] not in LEAD_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    WorkLog.reject(log_id, user_id)
    return jsonify({"message": "Rejected"}), 200


@other_bp.route('/worklogs/summary/<int:client_id>', methods=['GET'])
@jwt_required()
def get_client_worklog_summary(client_id):
    claims = get_jwt()
    if claims['role'] not in LEAD_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    summary = WorkLog.get_client_summary(
        client_id,
        request.args.get('start_date'),
        request.args.get('end_date')
    )
    return jsonify(summary), 200


@other_bp.route('/company/letterhead', methods=['GET'])
@jwt_required()
def get_letterhead():
    return jsonify(CompanySettings.get()), 200


@other_bp.route('/company/letterhead', methods=['PUT'])
@jwt_required()
def update_letterhead():
    claims = get_jwt()
    if claims['role'] != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    data = request.json
    allowed = ['company_name', 'company_address', 'company_phone',
               'company_email', 'company_website', 'company_logo_path']
    update_data = {k: v for k, v in data.items() if k in allowed}
    CompanySettings.update(**update_data)
    return jsonify({"message": "Settings updated"}), 200


@other_bp.route('/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    user_id = int(get_jwt_identity())
    unread_only = request.args.get('unread') == 'true'
    notifications = Notification.get_by_user(user_id, unread_only)
    return jsonify(notifications), 200


@other_bp.route('/notifications/<int:notification_id>/read', methods=['PUT', 'PATCH'])
@jwt_required()
def mark_notification_read(notification_id):
    Notification.mark_read(notification_id)
    return jsonify({"message": "Notification marked as read"}), 200


@other_bp.route('/files/upload', methods=['POST'])
@jwt_required()
def upload_file():
    user_id = int(get_jwt_identity())
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    client_id = request.form.get('client_id')
    task_id = request.form.get('task_id')
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    file_id = File.create(
        client_id=client_id, file_name=filename, file_path=filepath,
        file_type=file.content_type, uploaded_by=user_id, task_id=task_id
    )
    return jsonify({"message": "File uploaded", "file_id": file_id}), 201


@other_bp.route('/files', methods=['GET'])
@jwt_required()
def get_files():
    client_id = request.args.get('client_id')
    if not client_id:
        return jsonify({"error": "client_id required"}), 400
    files = File.get_by_client(int(client_id))
    return jsonify(files), 200
