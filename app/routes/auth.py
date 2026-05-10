from flask import Blueprint, request, jsonify, send_from_directory, make_response
from flask_jwt_extended import (
    jwt_required, get_jwt_identity, get_jwt,
    jwt_required as refresh_required,
)
from app.models.user import User
from app.utils.auth import verify_password, generate_token, generate_refresh_token, hash_password
from app.utils.validators import (
    is_valid_email, is_strong_password, sanitize_str, require_json
)
from werkzeug.utils import secure_filename
from app.utils.database import get_db_connection
import os

auth_bp = Blueprint('auth', __name__)

PROFILE_UPLOAD_FOLDER = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'uploads', 'profiles')
)
print(f"DEBUG: PROFILE_UPLOAD_FOLDER is {os.path.abspath(PROFILE_UPLOAD_FOLDER)}")
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(PROFILE_UPLOAD_FOLDER, exist_ok=True)

VALID_ROLES = {'admin', 'marketing_head', 'developer', 'smm', 'crm_head', 'client', 'team_lead', 'employee'}


# ── Login ─────────────────────────────────────────────────────
@auth_bp.route('/login', methods=['POST'])
@require_json
def login():
    data = request.get_json()
    email    = sanitize_str(data.get('email', ''))
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    if not is_valid_email(email):
        return jsonify({'error': 'Invalid email format'}), 400
    if len(password) > 128:
        return jsonify({'error': 'Invalid credentials'}), 401

    user = User.get_by_email(email.lower())
    if not user or not verify_password(password, user['password']):
        return jsonify({'error': 'Invalid email or password'}), 401

    access_token  = generate_token(user['id'], user['role'], user.get('organisation_id'))
    refresh_token = generate_refresh_token(user['id'], user['role'], user.get('organisation_id'))

    return jsonify({
        'token':         access_token,
        'refresh_token': refresh_token,
        'user': {
            'id':              user['id'],
            'name':            user['name'],
            'email':           user['email'],
            'role':            user['role'],
            'organisation_id': user.get('organisation_id'),
            'team_id':         user.get('team_id'),
            'department_id':   user.get('department_id'),
            'manager_id':      user.get('manager_id'),
        },
    }), 200


# ── Refresh access token ──────────────────────────────────────
@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    user_id = int(get_jwt_identity())
    claims  = get_jwt()
    role    = claims.get('role', '')
    org_id  = claims.get('organisation_id')
    new_token = generate_token(user_id, role, org_id)
    return jsonify({'token': new_token}), 200


# ── Current user ──────────────────────────────────────────────
@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user_id = int(get_jwt_identity())
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT u.id, u.name, u.email, u.role, u.phone, u.team_id, u.department_id, u.manager_id,
               u.profile_image, u.profile_image_data, u.bio, u.dob, u.address,
               u.emergency_contact_name, u.emergency_contact_phone,
               t.name as team_name, d.name as department_name,
               m.name as manager_name, u.created_at, u.organisation_id
        FROM users u
        LEFT JOIN teams t ON u.team_id = t.id
        LEFT JOIN departments d ON u.department_id = d.id
        LEFT JOIN users m ON u.manager_id = m.id
        WHERE u.id = %s
    """, (user_id,))
    user = cursor.fetchone()
    cursor.close(); conn.close()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    user.pop('password', None)
    # Return base64 data URL directly — no separate image HTTP request needed
    if user.get('profile_image_data'):
        user['profile_image'] = user['profile_image_data']
    elif user.get('profile_image'):
        try:
            path = os.path.join(PROFILE_UPLOAD_FOLDER, user['profile_image'])
            if os.path.exists(path):
                user['profile_image'] = f"{user['profile_image']}?t={int(os.path.getmtime(path))}"
        except Exception:
            pass
    user.pop('profile_image_data', None)
    return jsonify(user), 200


# ── List users ────────────────────────────────────────────────
@auth_bp.route('/users', methods=['GET'])
@jwt_required()
def get_users():
    claims        = get_jwt()
    org_id        = claims.get('organisation_id')
    role          = request.args.get('role')
    team_id       = request.args.get('team_id')
    department_id = request.args.get('department_id')

    if role and role not in VALID_ROLES:
        return jsonify({'error': 'Invalid role filter'}), 400

    users = User.get_all(
        role=role,
        team_id=int(team_id) if team_id and team_id.isdigit() else None,
        department_id=int(department_id) if department_id and department_id.isdigit() else None,
        organisation_id=org_id,
    )
    for u in users:
        u.pop('password', None)
    return jsonify(users), 200


# ── Register (publicly accessible for setup) ─────────────────
@auth_bp.route('/register', methods=['POST'])
@require_json
def register():
    from app.utils.database import get_db_connection
    # Allow first user (admin) to register freely, after that require admin JWT
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    cursor.close(); conn.close()

    if count > 0:
        # Require admin token for subsequent registrations
        from flask_jwt_extended import verify_jwt_in_request
        try:
            verify_jwt_in_request()
            claims = get_jwt()
            if claims.get('role') != 'admin':
                return jsonify({'error': 'Only admins can create users'}), 403
        except Exception:
            return jsonify({'error': 'Authorization required'}), 401

    data = request.get_json()

    name     = sanitize_str(data.get('name', ''))
    email    = sanitize_str(data.get('email', '')).lower()
    password = data.get('password', '')
    role     = sanitize_str(data.get('role', ''))

    # Required field validation
    errors = {}
    if not name or len(name) < 2:
        errors['name'] = 'Name must be at least 2 characters'
    if not is_valid_email(email):
        errors['email'] = 'Invalid email format'
    if not is_strong_password(password):
        errors['password'] = 'Password must be at least 8 characters with letters and numbers'
    if role not in VALID_ROLES:
        errors['role'] = f'Role must be one of: {", ".join(sorted(VALID_ROLES))}'
    if errors:
        return jsonify({'error': 'Validation failed', 'fields': errors}), 422

    # Check duplicate email
    if User.get_by_email(email):
        return jsonify({'error': 'A user with this email already exists'}), 409

    try:
        user_id = User.create(
            name=name,
            email=email,
            password=password,
            role=role,
            phone=sanitize_str(data.get('phone', ''), 20) or None,
            team_id=int(data['team_id']) if str(data.get('team_id', '')).isdigit() else None,
            department_id=int(data['department_id']) if str(data.get('department_id', '')).isdigit() else None,
            manager_id=int(data['manager_id']) if str(data.get('manager_id', '')).isdigit() else None,
        )
        return jsonify({'message': 'User created successfully', 'user_id': user_id}), 201
    except Exception as e:
        return jsonify({'error': 'Failed to create user', 'detail': str(e)}), 400


# ── Change password ───────────────────────────────────────────
@auth_bp.route('/change-password', methods=['POST'])
@jwt_required()
@require_json
def change_password():
    user_id      = int(get_jwt_identity())
    data         = request.get_json()
    current_pass = data.get('current_password', '')
    new_pass     = data.get('new_password', '')

    if not current_pass or not new_pass:
        return jsonify({'error': 'current_password and new_password are required'}), 400
    if not is_strong_password(new_pass):
        return jsonify({'error': 'New password must be at least 8 characters with letters and numbers'}), 422
    if current_pass == new_pass:
        return jsonify({'error': 'New password must differ from current password'}), 422

    user = User.get_by_id(user_id)
    if not user or not verify_password(current_pass, user['password']):
        return jsonify({'error': 'Current password is incorrect'}), 401

    User.update(user_id, password=hash_password(new_pass))
    return jsonify({'message': 'Password updated successfully'}), 200


# ── Update Profile (Self) ─────────────────────────────────────
@auth_bp.route('/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    allowed = ['name', 'phone', 'bio', 'dob', 'address', 'emergency_contact_name', 'emergency_contact_phone']
    update_data = {}
    for k in allowed:
        if k in data:
            update_data[k] = sanitize_str(str(data[k])) if data[k] else None

    if not update_data:
        return jsonify({'error': 'No valid fields provided'}), 400

    User.update(user_id, **update_data)
    return jsonify({'message': 'Profile updated successfully'}), 200


# ── Upload Profile Image ───────────────────────────────────────
@auth_bp.route('/profile/image', methods=['POST'])
@jwt_required()
def upload_profile_image():
    try:
        user_id = int(get_jwt_identity())

        if 'image' not in request.files:
            return jsonify({'error': 'No image provided in request'}), 400
        file = request.files['image']
        if not file or file.filename == '':
            return jsonify({'error': 'No image selected'}), 400

        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            return jsonify({'error': f'Invalid image type. Allowed: {", ".join(ALLOWED_IMAGE_EXTENSIONS)}'}), 400

        import base64
        file_bytes = file.read()
        if len(file_bytes) > 5 * 1024 * 1024:  # 5MB limit
            return jsonify({'error': 'Image too large. Max 5MB.'}), 400

        mime = f'image/{ext}' if ext != 'jpg' else 'image/jpeg'
        b64  = base64.b64encode(file_bytes).decode('utf-8')
        data_url = f'data:{mime};base64,{b64}'

        filename = secure_filename(f'profile_{user_id}.{ext}')
        User.update(user_id, profile_image=filename, profile_image_data=data_url)

        # Also save to disk as fallback (best effort)
        try:
            filepath = os.path.join(PROFILE_UPLOAD_FOLDER, filename)
            with open(filepath, 'wb') as f:
                f.write(file_bytes)
        except Exception:
            pass

        return jsonify({'message': 'Profile image updated', 'profile_image': filename}), 200

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': 'Upload failed', 'detail': str(e)}), 500


# ── Serve Profile Image (fallback for direct URL access) ───────
@auth_bp.route('/profile/image/<filename>', methods=['GET'])
def serve_profile_image(filename):
    # Try filesystem first
    filepath = os.path.join(PROFILE_UPLOAD_FOLDER, filename)
    if os.path.exists(filepath):
        response = make_response(send_from_directory(PROFILE_UPLOAD_FOLDER, filename))
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    # Fallback: serve from DB
    from app.utils.database import get_db_connection
    import base64, re
    try:
        conn   = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT profile_image_data FROM users WHERE profile_image = %s LIMIT 1',
                       (filename.split('?')[0],))
        row = cursor.fetchone()
        cursor.close(); conn.close()
        if row and row.get('profile_image_data'):
            data_url = row['profile_image_data']
            match = re.match(r'data:(image/[^;]+);base64,(.+)', data_url)
            if match:
                mime, b64 = match.group(1), match.group(2)
                img_bytes = base64.b64decode(b64)
                response  = make_response(img_bytes)
                response.headers['Content-Type']               = mime
                response.headers['Access-Control-Allow-Origin'] = '*'
                return response
    except Exception:
        pass
    return jsonify({'error': 'Image not found'}), 404


# ── Update User (Admin/HR) ───────────────────────────────────
@auth_bp.route('/users/<int:target_user_id>', methods=['PUT'])
@jwt_required()
@require_json
def update_user(target_user_id):
    claims = get_jwt()
    if claims.get('role') != 'admin':
        return jsonify({'error': 'Only admins can update user details'}), 403
        
    data = request.get_json()
    allowed = ['name', 'email', 'role', 'phone', 'team_id', 'department_id', 'manager_id']
    update_data = {k: v for k, v in data.items() if k in allowed}
    
    if 'email' in update_data:
        update_data['email'] = update_data['email'].lower()
        existing = User.get_by_email(update_data['email'])
        if existing and existing['id'] != target_user_id:
            return jsonify({'error': 'Email already in use'}), 409
            
    if 'role' in update_data and update_data['role'] not in VALID_ROLES:
        return jsonify({'error': 'Invalid role'}), 400
        
    if 'password' in data and data['password']:
        if not is_strong_password(data['password']):
            return jsonify({'error': 'Password is too weak'}), 422
        update_data['password'] = hash_password(data['password'])

    User.update(target_user_id, **update_data)
    return jsonify({'message': 'User updated successfully'}), 200
