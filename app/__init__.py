from flask import Flask, jsonify, request, make_response
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import os
import logging

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('kairaflow')

app = Flask(__name__)

app.config['JWT_SECRET_KEY']            = os.getenv('JWT_SECRET_KEY', 'change-me-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES']  = False
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = False
app.config['JWT_ERROR_MESSAGE_KEY']     = 'error'
app.config['MAX_CONTENT_LENGTH']        = 16 * 1024 * 1024

ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    'ALLOWED_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000'
).split(',') if o.strip()]

logger.info('ALLOWED_ORIGINS: %s', ALLOWED_ORIGINS)


def add_cors(response):
    origin = request.headers.get('Origin', '')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin']      = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods']     = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers']     = 'Content-Type, Authorization, X-Requested-With'
        response.headers['Access-Control-Max-Age']           = '600'
    return response


@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        res = make_response('', 200)
        return add_cors(res)


@app.after_request
def after_request(response):
    add_cors(response)
    if request.method != 'OPTIONS':
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options']        = 'DENY'
        response.headers['X-XSS-Protection']       = '1; mode=block'
        response.headers['Referrer-Policy']        = 'strict-origin-when-cross-origin'
        response.headers.pop('Server', None)
    return response


jwt = JWTManager(app)


@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({'error': 'Token has expired', 'code': 'token_expired'}), 401

@jwt.invalid_token_loader
def invalid_token_callback(reason):
    return jsonify({'error': 'Invalid token', 'code': 'invalid_token'}), 401

@jwt.unauthorized_loader
def missing_token_callback(reason):
    return jsonify({'error': 'Authorization token required', 'code': 'missing_token'}), 401

@jwt.revoked_token_loader
def revoked_token_callback(jwt_header, jwt_payload):
    return jsonify({'error': 'Token has been revoked', 'code': 'token_revoked'}), 401


limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=['300 per minute'],
    storage_uri='memory://',
)


@app.errorhandler(400)
def bad_request(e):
    return jsonify({'error': 'Bad request'}), 400

@app.errorhandler(401)
def unauthorized(e):
    return jsonify({'error': 'Unauthorized'}), 401

@app.errorhandler(403)
def forbidden(e):
    return jsonify({'error': 'Forbidden'}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({'error': 'Method not allowed'}), 405

@app.errorhandler(413)
def payload_too_large(e):
    return jsonify({'error': 'Payload too large'}), 413

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({'error': 'Too many requests', 'code': 'rate_limited'}), 429

@app.errorhandler(500)
def internal_error(e):
    logger.exception('Unhandled server error')
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(Exception)
def unhandled_exception(e):
    logger.exception('Unhandled exception: %s', str(e))
    return jsonify({'error': 'Internal server error'}), 500


# ── Blueprints ────────────────────────────────────────────────
from app.routes.auth import auth_bp
from app.routes.clients import client_bp
from app.routes.tasks import task_bp
from app.routes.other import other_bp
from app.routes.dashboard import dashboard_bp
from app.routes.org import org_bp
from app.routes.reports import reports_bp
from app.routes.attendance import attendance_bp
from app.routes.activity import activity_bp
from app.routes.hr import hr_bp
from app.routes.feedback import feedback_bp
from app.routes.analytics import analytics_bp
from app.routes.proposals import proposals_bp
from app.routes.messages import messages_bp
from app.routes.announcements import announcements_bp
from app.routes.documents import documents_bp
from app.routes.domain import domain_bp
from app.routes.superadmin import superadmin_bp
from app.routes.eod import eod_bp
from app.routes.salary import salary_bp
from app.routes.leads import leads_bp
from app.routes.calendar import calendar_bp
from app.routes.client_profile import client_profile_bp
from app.routes.lead_activity import lead_activity_bp
from app.routes.finance import finance_bp

app.register_blueprint(auth_bp,          url_prefix='/api/auth')
app.register_blueprint(client_bp,        url_prefix='/api')
app.register_blueprint(task_bp,          url_prefix='/api')
app.register_blueprint(other_bp,         url_prefix='/api')
app.register_blueprint(dashboard_bp,     url_prefix='/api')
app.register_blueprint(org_bp,           url_prefix='/api')
app.register_blueprint(reports_bp,       url_prefix='/api')
app.register_blueprint(attendance_bp,    url_prefix='/api')
app.register_blueprint(activity_bp,      url_prefix='/api')
app.register_blueprint(hr_bp,            url_prefix='/api')
app.register_blueprint(feedback_bp,      url_prefix='/api')
app.register_blueprint(analytics_bp,     url_prefix='/api')
app.register_blueprint(proposals_bp,     url_prefix='/api')
app.register_blueprint(messages_bp,      url_prefix='/api/messages')
app.register_blueprint(announcements_bp, url_prefix='/api')
app.register_blueprint(documents_bp,     url_prefix='/api/documents')
app.register_blueprint(domain_bp,        url_prefix='/api')
app.register_blueprint(superadmin_bp,    url_prefix='/api/superadmin')
app.register_blueprint(eod_bp,           url_prefix='/api')
app.register_blueprint(salary_bp,        url_prefix='/api')
app.register_blueprint(leads_bp,         url_prefix='/api')
app.register_blueprint(calendar_bp,      url_prefix='/api')
app.register_blueprint(client_profile_bp, url_prefix='/api')
app.register_blueprint(lead_activity_bp, url_prefix='/api')
app.register_blueprint(finance_bp,       url_prefix='/api')

limiter.limit('10 per minute', methods=['GET','POST','PUT','PATCH','DELETE'])(auth_bp)


@app.route('/')
def index():
    return jsonify({'status': 'ok', 'service': 'KairaFlow API'}), 200

@app.route('/health')
def health():
    from app.utils.database import get_db_connection
    try:
        conn = get_db_connection()
        conn.ping(reconnect=False)
        conn.close()
        db_status = 'ok'
    except Exception:
        db_status = 'error'
    return jsonify({'status': 'ok', 'db': db_status}), 200
