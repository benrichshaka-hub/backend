from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.models.client_profile import ClientProfile

client_profile_bp = Blueprint('client_profile', __name__)

ADMIN_ROLES  = ['admin', 'marketing_head', 'crm_head']
VIEWER_ROLES = ['admin', 'marketing_head', 'crm_head', 'team_lead']


@client_profile_bp.route('/clients/<int:client_id>/profiles', methods=['GET'])
@jwt_required()
def get_profiles(client_id):
    claims = get_jwt()
    if claims['role'] not in VIEWER_ROLES:
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify(ClientProfile.get_by_client(client_id)), 200


@client_profile_bp.route('/clients/<int:client_id>/profiles', methods=['POST'])
@jwt_required()
def create_profile(client_id):
    claims = get_jwt()
    if claims['role'] not in VIEWER_ROLES:   # team_lead can add
        return jsonify({'error': 'Unauthorized'}), 403
    user_id = int(get_jwt_identity())
    data = request.json or {}
    profile_id = ClientProfile.create(client_id, user_id, **data)
    return jsonify({'message': 'Profile created', 'profile_id': profile_id}), 201


@client_profile_bp.route('/clients/profiles/<int:profile_id>', methods=['PUT'])
@jwt_required()
def update_profile(profile_id):
    claims = get_jwt()
    if claims['role'] not in ADMIN_ROLES:    # team_lead cannot edit
        return jsonify({'error': 'Unauthorized'}), 403
    user_id = int(get_jwt_identity())
    data = request.json or {}
    ClientProfile.update(profile_id, user_id, **data)
    return jsonify({'message': 'Profile updated'}), 200


@client_profile_bp.route('/clients/profiles/<int:profile_id>', methods=['DELETE'])
@jwt_required()
def delete_profile(profile_id):
    claims = get_jwt()
    if claims['role'] not in ADMIN_ROLES:    # team_lead cannot delete
        return jsonify({'error': 'Unauthorized'}), 403
    user_id = int(get_jwt_identity())
    ClientProfile.delete(profile_id, user_id)
    return jsonify({'message': 'Profile deleted'}), 200


@client_profile_bp.route('/clients/profiles/<int:profile_id>/logs', methods=['GET'])
@jwt_required()
def get_profile_logs(profile_id):
    claims = get_jwt()
    if claims['role'] not in VIEWER_ROLES:
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify(ClientProfile.get_logs(profile_id)), 200
