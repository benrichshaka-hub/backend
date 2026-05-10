from flask import Blueprint, request, jsonify, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.utils.database import get_db_connection
from werkzeug.utils import secure_filename
from datetime import datetime, date
from decimal import Decimal
import os

documents_bp = Blueprint('documents', __name__)
documents_bp.strict_slashes = False

UPLOAD_FOLDER = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'uploads', 'documents')
)
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'png', 'jpg', 'jpeg', 'gif', 'zip', 'csv'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def serialize(row):
    out = {}
    for k, v in row.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


@documents_bp.route('/', methods=['GET'])
@jwt_required()
def get_documents():
    claims = get_jwt()
    org_id = claims.get('organisation_id')
    conn   = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    org_f  = "AND u.organisation_id = %s" if org_id is not None else ""
    params = ([org_id] if org_id is not None else [])
    cursor.execute(f'''
        SELECT d.id, d.title, d.description, d.file_url, d.file_name, d.file_type, d.file_size,
               d.uploaded_at, d.uploader_id, u.name as uploader_name, u.role as uploader_role
        FROM documents d
        JOIN users u ON d.uploader_id = u.id
        WHERE 1=1 {org_f}
        ORDER BY d.uploaded_at DESC
    ''', params)
    rows = cursor.fetchall() or []
    cursor.close(); conn.close()
    return jsonify([serialize(r) for r in rows]), 200


@documents_bp.route('/', methods=['POST'])
@jwt_required()
def upload_document():
    user_id = int(get_jwt_identity())

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    title = request.form.get('title', file.filename)
    description = request.form.get('description', '')

    if not file.filename or not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400

    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    file_size = os.path.getsize(filepath)
    file_type = file.content_type

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO documents (uploader_id, title, description, file_url, file_name, file_type, file_size, uploaded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (user_id, title, description, filename, file.filename, file_type, file_size, datetime.now()))
        conn.commit()
        doc_id = cursor.lastrowid
        cursor.close(); conn.close()
        return jsonify({'message': 'Document uploaded', 'id': doc_id, 'file_url': filename}), 201
    except Exception as e:
        conn.rollback(); cursor.close(); conn.close()
        return jsonify({'error': str(e)}), 500


@documents_bp.route('/<int:doc_id>', methods=['DELETE'])
@jwt_required()
def delete_document(doc_id):
    user_id = int(get_jwt_identity())
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT uploader_id, file_url FROM documents WHERE id = %s', (doc_id,))
    doc = cursor.fetchone()

    if not doc:
        cursor.close(); conn.close()
        return jsonify({'error': 'Document not found'}), 404

    cursor.execute('SELECT role FROM users WHERE id = %s', (user_id,))
    user = cursor.fetchone()
    if doc['uploader_id'] != user_id and user['role'] != 'admin':
        cursor.close(); conn.close()
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        cursor.execute('DELETE FROM documents WHERE id = %s', (doc_id,))
        conn.commit()
        filepath = os.path.join(UPLOAD_FOLDER, doc['file_url'])
        if os.path.exists(filepath):
            os.remove(filepath)
        cursor.close(); conn.close()
        return jsonify({'message': 'Document deleted'}), 200
    except Exception as e:
        conn.rollback(); cursor.close(); conn.close()
        return jsonify({'error': str(e)}), 500


@documents_bp.route('/download/<filename>', methods=['GET'])
@jwt_required()
def download_document(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)
