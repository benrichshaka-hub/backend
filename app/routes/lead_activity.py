from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.models.lead_activity import LeadActivity
from app.models.lead import Lead
from datetime import datetime
from zoneinfo import ZoneInfo

lead_activity_bp = Blueprint('lead_activity', __name__)
ALLOWED = ['admin', 'crm', 'crm_head', 'marketing_head', 'smm', 'team_lead']
ADMIN   = ['admin', 'crm_head', 'marketing_head']
IST     = ZoneInfo('Asia/Kolkata')


@lead_activity_bp.route('/leads/<int:lead_id>/activities', methods=['GET'])
@jwt_required()
def get_activities(lead_id):
    claims = get_jwt()
    if claims['role'] not in ALLOWED:
        return jsonify({'error': 'Unauthorized'}), 403
    activities = LeadActivity.get_by_lead(lead_id)
    history    = LeadActivity.get_status_history(lead_id)
    return jsonify({'activities': activities, 'status_history': history}), 200


@lead_activity_bp.route('/leads/<int:lead_id>/activities', methods=['POST'])
@jwt_required()
def add_activity(lead_id):
    claims  = get_jwt()
    if claims['role'] not in ALLOWED:
        return jsonify({'error': 'Unauthorized'}), 403
    user_id = int(get_jwt_identity())
    data    = request.json or {}

    if not data.get('notes'):
        return jsonify({'error': 'notes required'}), 400
    if not data.get('comm_type'):
        return jsonify({'error': 'comm_type required'}), 400

    now = datetime.now(IST)
    activity_date = data.get('activity_date', now.strftime('%Y-%m-%d'))
    activity_time = data.get('activity_time', now.strftime('%H:%M'))

    act_id = LeadActivity.add(
        lead_id=lead_id,
        user_id=user_id,
        comm_type=data['comm_type'],
        notes=data['notes'],
        status_after=data.get('status_after'),
        next_followup_date=data.get('next_followup_date'),
        activity_date=activity_date,
        activity_time=activity_time,
    )

    # Update lead status if provided
    if data.get('status_after'):
        lead = Lead.get_by_id(lead_id)
        if lead and lead['status'] != data['status_after']:
            LeadActivity.add_status_history(lead_id, user_id, lead['status'], data['status_after'])
            Lead.update(lead_id, status=data['status_after'])

    return jsonify({'message': 'Activity added', 'id': act_id}), 201


@lead_activity_bp.route('/leads/activities/<int:activity_id>', methods=['DELETE'])
@jwt_required()
def delete_activity(activity_id):
    claims = get_jwt()
    if claims['role'] not in ADMIN:
        return jsonify({'error': 'Unauthorized'}), 403
    LeadActivity.delete(activity_id)
    return jsonify({'message': 'Deleted'}), 200


@lead_activity_bp.route('/leads/analytics', methods=['GET'])
@jwt_required()
def get_analytics():
    claims = get_jwt()
    if claims['role'] not in ALLOWED:
        return jsonify({'error': 'Unauthorized'}), 403
    org_id = claims.get('organisation_id')
    data   = LeadActivity.get_analytics(organisation_id=org_id)
    return jsonify(data), 200
