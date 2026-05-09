import json
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.utils.database import get_db_connection
from app.models.notification import Notification

announcements_bp = Blueprint('announcements', __name__)


@announcements_bp.route('/announcements', methods=['GET'])
@jwt_required()
def get_announcements():
    user_id = int(get_jwt_identity())
    claims = get_jwt()
    org_id = claims.get('organisation_id')
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    org_f  = "AND a.organisation_id = %s" if org_id is not None else ""
    params = ([org_id] if org_id is not None else [])
    cursor.execute(f'''
        SELECT a.*, u.name as sender_name, u.role as sender_role, u.profile_image as sender_image,
               (SELECT COUNT(*) FROM announcement_comments WHERE announcement_id = a.id) as comment_count,
               (SELECT COUNT(*) FROM announcement_likes WHERE announcement_id = a.id) as like_count,
               (SELECT COUNT(*) FROM announcement_likes WHERE announcement_id = a.id AND user_id = %s) as user_liked
        FROM announcements a
        JOIN users u ON a.created_by = u.id
        WHERE 1=1 {org_f}
        ORDER BY a.is_pinned DESC, a.created_at DESC
    ''', [user_id] + params)
    announcements = cursor.fetchall() or []
    # Parse JSON poll_data if exists and add mtime to image
    from app.routes.auth import PROFILE_UPLOAD_FOLDER
    import os
    for ann in announcements:
        if ann.get('poll_data'):
            try: ann['poll_data'] = json.loads(ann['poll_data'])
            except: pass
        if ann.get('sender_image'):
            try:
                path = os.path.join(PROFILE_UPLOAD_FOLDER, ann['sender_image'])
                if os.path.exists(path):
                    ann['sender_image'] = f"{ann['sender_image']}?t={int(os.path.getmtime(path))}"
            except: pass
    cursor.close(); conn.close()
    return jsonify(announcements), 200


@announcements_bp.route('/announcements', methods=['POST'])
@jwt_required()
def create_announcement():
    user_id = int(get_jwt_identity())
    claims  = get_jwt()
    org_id  = claims.get('organisation_id')
    if claims.get('role') not in ['admin', 'superadmin', 'marketing_head', 'crm_head', 'crm', 'team_lead', 'hr']:
        return jsonify({'error': 'Only leadership can create announcements'}), 403
    data    = request.get_json()
    title   = data.get('title')
    content = data.get('content')
    poll    = data.get('poll_data') # Expected: {"question": "...", "options": ["opt1", "opt2"]}
    
    if poll:
        # Format for DB storage: {"question": "...", "options": [{"text": "...", "votes": []}]}
        poll = {
            "question": poll.get("question"),
            "options": [{"text": opt, "votes": []} for opt in poll.get("options", [])]
        }

    if not title or not content:
        return jsonify({'error': 'Title and content are required'}), 400
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO announcements (title, content, created_by, organisation_id, poll_data) VALUES (%s, %s, %s, %s, %s)',
            (title, content, user_id, org_id, json.dumps(poll) if poll else None)
        )
        ann_id = cursor.lastrowid
        conn.commit()
        cursor.close(); conn.close()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    # Fetch users to notify
    try:
        conn2   = get_db_connection()
        cursor2 = conn2.cursor()
        org_f   = "AND organisation_id = %s" if org_id is not None else ""
        params  = ([org_id] if org_id is not None else []) + [user_id]
        cursor2.execute(f'SELECT id FROM users WHERE 1=1 {org_f} AND id != %s', params)
        user_ids = [row[0] for row in cursor2.fetchall()]
        cursor2.close(); conn2.close()
    except Exception:
        user_ids = []

    if user_ids:
        try:
            conn3 = get_db_connection()
            cursor3 = conn3.cursor()
            for uid in user_ids:
                cursor3.execute("""
                    INSERT INTO notifications (user_id, type, title, message, link)
                    VALUES (%s, 'announcement', '📢 Official Announcement', %s, '/dashboard/announcements')
                """, (uid, f"New announcement: {title}"))
            conn3.commit()
            cursor3.close(); conn3.close()
        except Exception as e:
            print(f"Notification bulk error: {e}")

    return jsonify({'message': 'Announcement created', 'id': ann_id}), 201


@announcements_bp.route('/announcements/<int:ann_id>/like', methods=['POST'])
@jwt_required()
def toggle_like(ann_id):
    user_id = int(get_jwt_identity())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM announcement_likes WHERE announcement_id=%s AND user_id=%s", (ann_id, user_id))
    if cursor.fetchone():
        cursor.execute("DELETE FROM announcement_likes WHERE announcement_id=%s AND user_id=%s", (ann_id, user_id))
        action = 'unliked'
    else:
        cursor.execute("INSERT INTO announcement_likes (announcement_id, user_id) VALUES (%s, %s)", (ann_id, user_id))
        action = 'liked'
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"message": f"Announcement {action}", "action": action}), 200


@announcements_bp.route('/announcements/<int:ann_id>/view', methods=['POST'])
@jwt_required()
def record_view(ann_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE announcements SET views = views + 1 WHERE id = %s", (ann_id,))
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"message": "View recorded"}), 200


@announcements_bp.route('/announcements/<int:ann_id>/pin', methods=['POST'])
@jwt_required()
def toggle_pin(ann_id):
    claims = get_jwt()
    if claims.get('role') not in ['admin', 'superadmin', 'crm_head', 'marketing_head']:
        return jsonify({"error": "Unauthorized"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE announcements SET is_pinned = 1 - is_pinned WHERE id = %s", (ann_id,))
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"message": "Pin status toggled"}), 200


@announcements_bp.route('/announcements/<int:ann_id>/vote', methods=['POST'])
@jwt_required()
def vote_poll(ann_id):
    user_id = int(get_jwt_identity())
    data = request.get_json()
    option_index = data.get('option_index')
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT poll_data FROM announcements WHERE id = %s", (ann_id,))
    res = cursor.fetchone()
    if not res or not res['poll_data']:
        cursor.close(); conn.close()
        return jsonify({"error": "No poll found"}), 404
        
    poll = json.loads(res['poll_data'])
    
    # Remove previous votes by this user
    for opt in poll['options']:
        if user_id in opt['votes']:
            opt['votes'].remove(user_id)
            
    # Add new vote
    if option_index is not None and option_index < len(poll['options']):
        poll['options'][option_index]['votes'].append(user_id)
        
    cursor.execute("UPDATE announcements SET poll_data = %s WHERE id = %s", (json.dumps(poll), ann_id))
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"message": "Vote recorded", "poll_data": poll}), 200


@announcements_bp.route('/announcements/<int:ann_id>', methods=['PUT', 'DELETE'])
@jwt_required()
def manage_announcement(ann_id):
    claims = get_jwt()
    if claims.get('role') not in ['admin', 'superadmin', 'marketing_head', 'crm_head', 'team_lead']:
        return jsonify({'error': 'Unauthorized'}), 403
    conn   = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'DELETE':
        cursor.execute('DELETE FROM announcements WHERE id = %s', (ann_id,))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({'message': 'Announcement deleted'}), 200
    data = request.get_json()
    cursor.execute('UPDATE announcements SET title=%s, content=%s WHERE id=%s', (data.get('title'), data.get('content'), ann_id))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({'message': 'Announcement updated'}), 200


@announcements_bp.route('/announcements/<int:ann_id>/comments', methods=['GET', 'POST'])
@jwt_required()
def manage_comments(ann_id):
    user_id = int(get_jwt_identity())
    conn    = get_db_connection()
    cursor  = conn.cursor(dictionary=True)
    if request.method == 'POST':
        data    = request.get_json()
        content = data.get('content')
        if not content:
            cursor.close(); conn.close()
            return jsonify({'error': 'Comment content required'}), 400
        cursor.execute('INSERT INTO announcement_comments (announcement_id, user_id, content) VALUES (%s,%s,%s)', (ann_id, user_id, content))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({'message': 'Comment added'}), 201
    cursor.execute('''
        SELECT c.*, u.name as user_name, u.role as user_role, u.profile_image as user_image
        FROM announcement_comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.announcement_id = %s ORDER BY c.created_at ASC
    ''', (ann_id,))
    comments = cursor.fetchall() or []
    from app.routes.auth import PROFILE_UPLOAD_FOLDER
    import os
    for c in comments:
        if c.get('user_image'):
            try:
                path = os.path.join(PROFILE_UPLOAD_FOLDER, c['user_image'])
                if os.path.exists(path):
                    c['user_image'] = f"{c['user_image']}?t={int(os.path.getmtime(path))}"
            except: pass
    cursor.close(); conn.close()
    return jsonify(comments), 200
