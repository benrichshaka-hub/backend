from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.models.finance import ClientPayment
from app.models.client import Client

finance_bp = Blueprint('finance', __name__)

ALLOWED_ROLES = ['admin', 'crm', 'crm_head', 'marketing_head']


@finance_bp.route('/finance/summary', methods=['GET'])
@jwt_required()
def get_all_finance():
    claims = get_jwt()
    if claims['role'] not in ALLOWED_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    org_id = claims.get('organisation_id')
    rows = ClientPayment.get_all_finance_summary(organisation_id=org_id)
    return jsonify(rows), 200


@finance_bp.route('/finance/stats', methods=['GET'])
@jwt_required()
def get_finance_stats():
    claims = get_jwt()
    if claims['role'] not in ALLOWED_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    org_id = claims.get('organisation_id')
    stats = ClientPayment.get_overall_stats(organisation_id=org_id)
    return jsonify(stats), 200


@finance_bp.route('/finance/clients/<int:client_id>', methods=['GET'])
@jwt_required()
def get_client_finance(client_id):
    claims = get_jwt()
    if claims['role'] not in ALLOWED_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    summary = ClientPayment.get_client_finance_summary(client_id)
    if not summary:
        return jsonify({"error": "Client not found"}), 404
    payments = ClientPayment.get_payments_by_client(client_id)
    summary['payments'] = payments
    return jsonify(summary), 200


@finance_bp.route('/finance/clients/<int:client_id>/payments', methods=['POST'])
@jwt_required()
def add_payment(client_id):
    claims = get_jwt()
    if claims['role'] not in ALLOWED_ROLES:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json
    if not data.get('amount') or not data.get('payment_date'):
        return jsonify({"error": "amount and payment_date are required"}), 400

    try:
        added_by = int(get_jwt_identity())
        payment_id = ClientPayment.add_payment(
            client_id=client_id,
            amount=data['amount'],
            payment_date=data['payment_date'],
            payment_method=data.get('payment_method', 'bank_transfer'),
            reference=data.get('reference', ''),
            notes=data.get('notes', ''),
            added_by=added_by
        )
        return jsonify({"message": "Payment added", "payment_id": payment_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@finance_bp.route('/finance/payments/<int:payment_id>', methods=['DELETE'])
@jwt_required()
def delete_payment(payment_id):
    claims = get_jwt()
    if claims['role'] not in ['admin']:
        return jsonify({"error": "Unauthorized"}), 403
    ClientPayment.delete_payment(payment_id)
    return jsonify({"message": "Payment deleted"}), 200


@finance_bp.route('/finance/clients/<int:client_id>/total', methods=['PUT'])
@jwt_required()
def update_total_amount(client_id):
    claims = get_jwt()
    if claims['role'] not in ALLOWED_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    data = request.json
    if data.get('total_amount') is None:
        return jsonify({"error": "total_amount required"}), 400
    Client.update(client_id, total_amount=data['total_amount'])
    return jsonify({"message": "Total amount updated"}), 200
@finance_bp.route('/finance/payments', methods=['GET'])
@jwt_required()
def get_all_payments():
    claims = get_jwt()
    if claims['role'] not in ALLOWED_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    org_id = claims.get('organisation_id')
    client_id = request.args.get('client_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    payments = ClientPayment.get_all_payments(
        client_id=client_id,
        start_date=start_date,
        end_date=end_date,
        organisation_id=org_id
    )
    return jsonify(payments), 200
