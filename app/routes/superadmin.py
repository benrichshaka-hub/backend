from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    jwt_required, get_jwt_identity, get_jwt,
    create_access_token, create_refresh_token
)
from datetime import timedelta, datetime
from app.models.superadmin import SuperAdmin
from app.models.organisation import Organisation
from app.models.user import User
from app.utils.auth import verify_password, hash_password
from app.utils.validators import is_valid_email, is_strong_password, sanitize_str, require_json
import re, random, smtplib, os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

superadmin_bp = Blueprint('superadmin', __name__)


# ── Helpers ───────────────────────────────────────────────────

def _sa_token(sa_id: int) -> str:
    return create_access_token(
        identity=str(sa_id),
        additional_claims={'role': 'superadmin', 'is_superadmin': True},
        expires_delta=timedelta(hours=8),
    )


def _sa_refresh_token(sa_id: int) -> str:
    return create_refresh_token(
        identity=str(sa_id),
        additional_claims={'role': 'superadmin', 'is_superadmin': True},
        expires_delta=timedelta(days=30),
    )


def _otp_pending_token(sa_id: int) -> str:
    """Short-lived token only used to call /verify-otp — no dashboard access."""
    return create_access_token(
        identity=str(sa_id),
        additional_claims={'role': 'superadmin', 'is_superadmin': False, 'otp_pending': True},
        expires_delta=timedelta(minutes=10),
    )


def _require_superadmin():
    claims = get_jwt()
    if not claims.get('is_superadmin'):
        return None, (jsonify({'error': 'Superadmin access required'}), 403)
    return int(get_jwt_identity()), None


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text[:80]


def _get_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr)


def _send_otp_email(to_email: str, to_name: str, otp: str):
    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', 587))
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASS')

    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'KairaFlow SuperAdmin — Your OTP Code'
    msg['From']    = f'KairaFlow Security <{smtp_user}>'
    msg['To']      = to_email

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;background:#0f1729;border-radius:16px;padding:32px;">
      <div style="text-align:center;margin-bottom:24px;">
        <div style="font-size:32px;">⚡</div>
        <h2 style="color:#ef4444;margin:8px 0;">KairaFlow SuperAdmin</h2>
        <p style="color:#9ca3af;font-size:13px;">Security Verification</p>
      </div>
      <p style="color:#e5e7eb;font-size:14px;">Hi <strong>{to_name}</strong>,</p>
      <p style="color:#9ca3af;font-size:13px;">Your one-time password (OTP) for SuperAdmin login is:</p>
      <div style="background:#1e293b;border:2px solid #ef4444;border-radius:12px;padding:24px;text-align:center;margin:20px 0;">
        <span style="font-size:40px;font-weight:900;letter-spacing:12px;color:#ef4444;font-family:monospace;">{otp}</span>
      </div>
      <p style="color:#9ca3af;font-size:12px;">⏱ This OTP expires in <strong style="color:#f59e0b;">10 minutes</strong>.</p>
      <p style="color:#9ca3af;font-size:12px;">🔒 If you did not request this, please secure your account immediately.</p>
      <hr style="border:1px solid #1e293b;margin:20px 0;">
      <p style="color:#4b5563;font-size:11px;text-align:center;">KairaFlow Platform · Automated Security Email</p>
    </div>
    """

    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())


def _generate_otp() -> str:
    return str(random.randint(100000, 999999))


def _save_otp(sa_id: int, otp: str):
    from app.utils.database import get_db_connection
    conn   = get_db_connection()
    cursor = conn.cursor()
    # Invalidate old OTPs
    cursor.execute("UPDATE superadmin_otps SET used=1 WHERE superadmin_id=%s AND used=0", (sa_id,))
    expires = datetime.utcnow() + timedelta(minutes=10)
    cursor.execute(
        "INSERT INTO superadmin_otps (superadmin_id, otp, expires_at) VALUES (%s, %s, %s)",
        (sa_id, otp, expires)
    )
    conn.commit()
    cursor.close(); conn.close()


def _verify_otp(sa_id: int, otp: str) -> bool:
    from app.utils.database import get_db_connection
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id FROM superadmin_otps
        WHERE superadmin_id=%s AND otp=%s AND used=0 AND expires_at > UTC_TIMESTAMP()
        ORDER BY created_at DESC LIMIT 1
    """, (sa_id, otp))
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE superadmin_otps SET used=1 WHERE id=%s", (row['id'],))
        conn.commit()
    cursor.close(); conn.close()
    return row is not None


# ── SuperAdmin Auth ───────────────────────────────────────────

@superadmin_bp.route('/login', methods=['POST'])
@require_json
def superadmin_login():
    data     = request.get_json()
    email    = sanitize_str(data.get('email', '')).lower()
    password = data.get('password', '')
    print(f"DEBUG LOGIN - Email: '{email}', Password length: {len(password)}, Raw password: '{password}'")

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    if not is_valid_email(email):
        return jsonify({'error': 'Invalid email format'}), 400

    sa = SuperAdmin.get_by_email(email)
    if not sa or not verify_password(password, sa['password']):
        return jsonify({'error': 'Invalid credentials'}), 401
    if not sa['is_active']:
        return jsonify({'error': 'Account is disabled'}), 403

    # Generate & send OTP
    otp = _generate_otp()
    _save_otp(sa['id'], otp)
    try:
        _send_otp_email(sa['email'], sa['name'], otp)
    except Exception as e:
        return jsonify({'error': f'Failed to send OTP email: {str(e)}'}), 500

    SuperAdmin.log_action(sa['id'], 'OTP_SENT', ip_address=_get_ip())

    # Return a short-lived pending token (cannot access dashboard)
    return jsonify({
        'otp_required': True,
        'otp_token':    _otp_pending_token(sa['id']),
        'message':      f'OTP sent to {sa["email"][:3]}***{sa["email"][sa["email"].index("@"):]}'
    }), 200


@superadmin_bp.route('/verify-otp', methods=['POST'])
@jwt_required()
@require_json
def verify_otp():
    claims = get_jwt()
    if not claims.get('otp_pending'):
        return jsonify({'error': 'Invalid token for OTP verification'}), 403

    sa_id = int(get_jwt_identity())
    otp   = sanitize_str(request.get_json().get('otp', ''))

    if not otp or len(otp) != 6 or not otp.isdigit():
        return jsonify({'error': 'OTP must be 6 digits'}), 400

    if not _verify_otp(sa_id, otp):
        return jsonify({'error': 'Invalid or expired OTP'}), 401

    sa = SuperAdmin.get_by_id(sa_id)
    SuperAdmin.log_action(sa_id, 'LOGIN', ip_address=_get_ip())

    return jsonify({
        'token':         _sa_token(sa_id),
        'refresh_token': _sa_refresh_token(sa_id),
        'superadmin': {
            'id':    sa['id'],
            'name':  sa['name'],
            'email': sa['email'],
            'role':  'superadmin',
        }
    }), 200


@superadmin_bp.route('/resend-otp', methods=['POST'])
@jwt_required()
def resend_otp():
    claims = get_jwt()
    if not claims.get('otp_pending'):
        return jsonify({'error': 'Invalid token'}), 403
    sa_id = int(get_jwt_identity())
    sa    = SuperAdmin.get_by_id(sa_id)
    if not sa:
        return jsonify({'error': 'Not found'}), 404
    otp = _generate_otp()
    _save_otp(sa_id, otp)
    try:
        _send_otp_email(sa['email'], sa['name'], otp)
    except Exception as e:
        return jsonify({'error': f'Failed to send OTP: {str(e)}'}), 500
    return jsonify({'message': 'OTP resent successfully'}), 200


@superadmin_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def superadmin_refresh():
    claims = get_jwt()
    if not claims.get('is_superadmin'):
        return jsonify({'error': 'Superadmin access required'}), 403
    sa_id = int(get_jwt_identity())
    return jsonify({'token': _sa_token(sa_id)}), 200


@superadmin_bp.route('/me', methods=['GET'])
@jwt_required()
def superadmin_me():
    sa_id, err = _require_superadmin()
    if err:
        return err
    sa = SuperAdmin.get_by_id(sa_id)
    if not sa:
        return jsonify({'error': 'Superadmin not found'}), 404
    return jsonify(sa), 200


# ── Organisation Management ───────────────────────────────────

@superadmin_bp.route('/organisations', methods=['GET'])
@jwt_required()
def list_organisations():
    sa_id, err = _require_superadmin()
    if err:
        return err
    orgs = Organisation.get_all()
    return jsonify(orgs), 200


@superadmin_bp.route('/organisations/<int:org_id>', methods=['GET'])
@jwt_required()
def get_organisation(org_id):
    sa_id, err = _require_superadmin()
    if err:
        return err
    org = Organisation.get_by_id(org_id)
    if not org:
        return jsonify({'error': 'Organisation not found'}), 404
    return jsonify(org), 200


@superadmin_bp.route('/organisations', methods=['POST'])
@jwt_required()
@require_json
def create_organisation():
    sa_id, err = _require_superadmin()
    if err:
        return err

    data  = request.get_json()
    name  = sanitize_str(data.get('name', ''))
    email = sanitize_str(data.get('email', '')).lower()
    phone = sanitize_str(data.get('phone', '')) or None
    address = sanitize_str(data.get('address', '')) or None
    plan  = data.get('plan', 'trial')
    trial_ends_at = data.get('trial_ends_at')

    errors = {}
    if not name or len(name) < 2:
        errors['name'] = 'Organisation name must be at least 2 characters'
    if not is_valid_email(email):
        errors['email'] = 'Invalid email format'
    if plan not in ('trial', 'basic', 'pro', 'enterprise'):
        errors['plan'] = 'Invalid plan'
    if errors:
        return jsonify({'error': 'Validation failed', 'fields': errors}), 422

    if Organisation.get_by_email(email):
        return jsonify({'error': 'An organisation with this email already exists'}), 409

    slug = _slugify(name)
    base_slug = slug
    counter = 1
    while Organisation.get_by_slug(slug):
        slug = f"{base_slug}-{counter}"
        counter += 1

    try:
        org_id = Organisation.create(
            name=name, slug=slug, email=email,
            phone=phone, address=address,
            plan=plan, trial_ends_at=trial_ends_at
        )
        SuperAdmin.log_action(sa_id, 'CREATE_ORGANISATION', 'organisation', org_id,
                              {'name': name, 'email': email}, _get_ip())
        return jsonify({'message': 'Organisation created', 'org_id': org_id, 'slug': slug}), 201
    except Exception as e:
        return jsonify({'error': 'Failed to create organisation', 'detail': str(e)}), 400


@superadmin_bp.route('/organisations/<int:org_id>', methods=['PUT'])
@jwt_required()
@require_json
def update_organisation(org_id):
    sa_id, err = _require_superadmin()
    if err:
        return err

    org = Organisation.get_by_id(org_id)
    if not org:
        return jsonify({'error': 'Organisation not found'}), 404

    data = request.get_json()
    allowed = ['name', 'email', 'phone', 'address', 'logo', 'is_active', 'plan', 'trial_ends_at']
    update_data = {k: v for k, v in data.items() if k in allowed}

    if 'email' in update_data:
        update_data['email'] = update_data['email'].lower()
        existing = Organisation.get_by_email(update_data['email'])
        if existing and existing['id'] != org_id:
            return jsonify({'error': 'Email already in use by another organisation'}), 409

    if not update_data:
        return jsonify({'error': 'No valid fields provided'}), 400

    Organisation.update(org_id, **update_data)
    SuperAdmin.log_action(sa_id, 'UPDATE_ORGANISATION', 'organisation', org_id,
                          update_data, _get_ip())
    return jsonify({'message': 'Organisation updated'}), 200


@superadmin_bp.route('/organisations/<int:org_id>/toggle', methods=['POST'])
@jwt_required()
def toggle_organisation(org_id):
    """Activate or deactivate an organisation."""
    sa_id, err = _require_superadmin()
    if err:
        return err

    org = Organisation.get_by_id(org_id)
    if not org:
        return jsonify({'error': 'Organisation not found'}), 404

    new_status = 0 if org['is_active'] else 1
    Organisation.update(org_id, is_active=new_status)
    action = 'ACTIVATE_ORGANISATION' if new_status else 'DEACTIVATE_ORGANISATION'
    SuperAdmin.log_action(sa_id, action, 'organisation', org_id, None, _get_ip())
    return jsonify({'message': f"Organisation {'activated' if new_status else 'deactivated'}",
                    'is_active': bool(new_status)}), 200


@superadmin_bp.route('/organisations/<int:org_id>', methods=['DELETE'])
@jwt_required()
def delete_organisation(org_id):
    sa_id, err = _require_superadmin()
    if err:
        return err

    org = Organisation.get_by_id(org_id)
    if not org:
        return jsonify({'error': 'Organisation not found'}), 404

    Organisation.delete(org_id)
    SuperAdmin.log_action(sa_id, 'DELETE_ORGANISATION', 'organisation', org_id,
                          {'name': org['name']}, _get_ip())
    return jsonify({'message': 'Organisation deleted'}), 200


# ── Organisation Users ────────────────────────────────────────

@superadmin_bp.route('/organisations/<int:org_id>/users', methods=['GET'])
@jwt_required()
def get_org_users(org_id):
    sa_id, err = _require_superadmin()
    if err:
        return err

    org = Organisation.get_by_id(org_id)
    if not org:
        return jsonify({'error': 'Organisation not found'}), 404

    users = Organisation.get_users(org_id)
    for u in users:
        u.pop('password', None)
    return jsonify(users), 200


@superadmin_bp.route('/organisations/<int:org_id>/admins', methods=['POST'])
@jwt_required()
@require_json
def create_org_admin(org_id):
    """Create an admin user for a specific organisation."""
    sa_id, err = _require_superadmin()
    if err:
        return err

    org = Organisation.get_by_id(org_id)
    if not org:
        return jsonify({'error': 'Organisation not found'}), 404
    if not org['is_active']:
        return jsonify({'error': 'Organisation is inactive'}), 403

    data     = request.get_json()
    name     = sanitize_str(data.get('name', ''))
    email    = sanitize_str(data.get('email', '')).lower()
    password = data.get('password', '')

    errors = {}
    if not name or len(name) < 2:
        errors['name'] = 'Name must be at least 2 characters'
    if not is_valid_email(email):
        errors['email'] = 'Invalid email format'
    if not is_strong_password(password):
        errors['password'] = 'Password must be at least 8 characters with letters and numbers'
    if errors:
        return jsonify({'error': 'Validation failed', 'fields': errors}), 422

    if User.get_by_email(email):
        return jsonify({'error': 'A user with this email already exists'}), 409

    try:
        user_id = User.create(
            name=name, email=email, password=password,
            role='admin',
            phone=sanitize_str(data.get('phone', ''), 20) or None,
        )
        # Assign to organisation
        User.update(user_id, organisation_id=org_id)
        SuperAdmin.log_action(sa_id, 'CREATE_ORG_ADMIN', 'user', user_id,
                              {'org_id': org_id, 'email': email}, _get_ip())
        return jsonify({'message': 'Organisation admin created', 'user_id': user_id}), 201
    except Exception as e:
        return jsonify({'error': 'Failed to create admin', 'detail': str(e)}), 400


@superadmin_bp.route('/organisations/<int:org_id>/users/<int:user_id>', methods=['DELETE'])
@jwt_required()
def remove_org_user(org_id, user_id):
    sa_id, err = _require_superadmin()
    if err:
        return err

    user = User.get_by_id(user_id)
    if not user or user.get('organisation_id') != org_id:
        return jsonify({'error': 'User not found in this organisation'}), 404

    User.delete(user_id)
    SuperAdmin.log_action(sa_id, 'DELETE_ORG_USER', 'user', user_id,
                          {'org_id': org_id}, _get_ip())
    return jsonify({'message': 'User removed'}), 200


# ── Platform Stats ────────────────────────────────────────────

@superadmin_bp.route('/stats', methods=['GET'])
@jwt_required()
def platform_stats():
    sa_id, err = _require_superadmin()
    if err:
        return err

    from app.utils.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        # Organisations
        cursor.execute("SELECT COUNT(*) as total FROM organisations")
        total_orgs = cursor.fetchone()['total']
        cursor.execute("SELECT COUNT(*) as total FROM organisations WHERE is_active = 1")
        active_orgs = cursor.fetchone()['total']

        # Users
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE organisation_id IS NOT NULL")
        total_users = cursor.fetchone()['total']
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE organisation_id IS NOT NULL AND role = 'admin'")
        total_admins = cursor.fetchone()['total']

        # Plans breakdown
        cursor.execute("SELECT plan, COUNT(*) as count FROM organisations GROUP BY plan")
        plans = cursor.fetchall()

        # Top organisations by user count
        cursor.execute("""
            SELECT o.id, o.name, o.slug, o.plan, o.is_active, o.created_at,
                   COUNT(u.id) as user_count
            FROM organisations o
            LEFT JOIN users u ON u.organisation_id = o.id
            GROUP BY o.id
            ORDER BY user_count DESC
            LIMIT 5
        """)
        top_orgs = cursor.fetchall()

        # Recent organisations
        cursor.execute("""
            SELECT id, name, email, plan, is_active, created_at
            FROM organisations
            ORDER BY created_at DESC LIMIT 5
        """)
        recent_orgs = cursor.fetchall()

        # Growth: orgs created per month (last 6 months)
        cursor.execute("""
            SELECT DATE_FORMAT(created_at, '%Y-%m') as month,
                   COUNT(*) as count
            FROM organisations
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)
            GROUP BY month ORDER BY month ASC
        """)
        growth = cursor.fetchall()

        # Recent audit logs
        cursor.execute("""
            SELECT al.action, al.created_at, al.ip_address,
                   sa.name as superadmin_name
            FROM superadmin_audit_logs al
            JOIN superadmins sa ON al.superadmin_id = sa.id
            ORDER BY al.created_at DESC LIMIT 10
        """)
        recent_activity = cursor.fetchall()

        cursor.close()
        return jsonify({
            'total_organisations':  total_orgs,
            'active_organisations': active_orgs,
            'inactive_organisations': total_orgs - active_orgs,
            'total_users':          total_users,
            'total_admins':         total_admins,
            'plans_breakdown':      plans,
            'top_organisations':    top_orgs,
            'recent_organisations': recent_orgs,
            'growth':               growth,
            'recent_activity':      recent_activity,
        }), 200
    finally:
        conn.close()


@superadmin_bp.route('/organisations/<int:org_id>/stats', methods=['GET'])
@jwt_required()
def get_org_stats(org_id):
    sa_id, err = _require_superadmin()
    if err:
        return err

    org = Organisation.get_by_id(org_id)
    if not org:
        return jsonify({'error': 'Organisation not found'}), 404

    from app.utils.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT COUNT(*) as total FROM users WHERE organisation_id = %s", (org_id,))
        total_users = cursor.fetchone()['total']

        cursor.execute("SELECT role, COUNT(*) as count FROM users WHERE organisation_id = %s GROUP BY role", (org_id,))
        roles = cursor.fetchall()

        cursor.execute("""
            SELECT u.id, u.name, u.email, u.role, u.created_at
            FROM users u WHERE u.organisation_id = %s
            ORDER BY u.created_at DESC LIMIT 5
        """, (org_id,))
        recent_users = cursor.fetchall()

        cursor.close()
        return jsonify({
            'organisation': org,
            'total_users':  total_users,
            'roles_breakdown': roles,
            'recent_users': recent_users,
        }), 200
    finally:
        conn.close()


# ── Audit Logs ────────────────────────────────────────────────

@superadmin_bp.route('/audit-logs', methods=['GET'])
@jwt_required()
def get_audit_logs():
    sa_id, err = _require_superadmin()
    if err:
        return err

    limit  = min(int(request.args.get('limit', 50)), 200)
    offset = int(request.args.get('offset', 0))
    logs   = SuperAdmin.get_audit_logs(limit=limit, offset=offset)
    return jsonify(logs), 200
