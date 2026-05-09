from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.models.task import Task
from app.models.other import Comment, Notification
from app.models.user import User
from app.utils.database import get_db_connection
from datetime import datetime

task_bp = Blueprint('task', __name__)

LEAD_ROLES = ['admin', 'team_lead', 'crm_head', 'marketing_head']

@task_bp.route('/tasks', methods=['POST'])
@jwt_required()
def create_task():
    data = request.json
    claims = get_jwt()
    assigned_by = int(get_jwt_identity())

    # Only admin and team leads can create/assign tasks
    if claims['role'] not in LEAD_ROLES:
        return jsonify({"error": "Only admins and team leads can create tasks"}), 403

    due_date = data.get('due_date') or None
    if due_date:
        try:
            due_dt = datetime.strptime(due_date, '%Y-%m-%d').date()
            if due_dt < datetime.now().date():
                return jsonify({"error": "Due date cannot be in the past"}), 400
        except ValueError:
            return jsonify({"error": "Invalid due date format. Use YYYY-MM-DD"}), 400

    try:
        assigned_to = int(data['assigned_to']) if data.get('assigned_to') else None
        task_id = Task.create(
            title=data['title'],
            description=data.get('description'),
            assigned_by=assigned_by,
            assigned_to=assigned_to,
            team_id=int(data['team_id']) if data.get('team_id') else None,
            department_id=int(data['department_id']) if data.get('department_id') else None,
            client_id=int(data['client_id']) if data.get('client_id') else None,
            department=data.get('department', 'general'),
            status=data.get('status', 'pending'),
            priority=data.get('priority', 'medium'),
            due_date=due_date,
            organisation_id=claims.get('organisation_id')
        )

        # Add participants
        for pid in data.get('participant_ids', []):
            try: Task.add_participant(task_id, int(pid))
            except: pass

        # Add observers
        for oid in data.get('observer_ids', []):
            try: Task.add_observer(task_id, int(oid))
            except: pass

        if assigned_to:
            assigner = User.get_by_id(assigned_by)
            Notification.create(
                assigned_to,
                "New Task Assigned",
                f"{assigner['name']} assigned you: {data['title']}",
                "task"
            )

        return jsonify({"message": "Task created", "task_id": task_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@task_bp.route('/tasks', methods=['GET'])
@jwt_required()
def get_tasks():
    from datetime import datetime, date
    from decimal import Decimal

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

    user_id = int(get_jwt_identity())
    claims = get_jwt()

    team_id = request.args.get('team_id')
    department_id = request.args.get('department_id')
    status = request.args.get('status')
    client_id = request.args.get('client_id')

    if client_id:
        tasks = Task.get_by_client(int(client_id))
    elif claims['role'] == 'admin':
        tasks = Task.get_all(
            team_id=int(team_id) if team_id else None,
            department_id=int(department_id) if department_id else None,
            status=status,
            organisation_id=claims.get('organisation_id')
        )
    elif claims['role'] in LEAD_ROLES:
        tasks = Task.get_for_team_lead(user_id)
    else:
        tasks = Task.get_by_user(user_id)
    return jsonify([serialize(t) for t in tasks]), 200


@task_bp.route('/tasks/<int:task_id>', methods=['GET'])
@jwt_required()
def get_task(task_id):
    from datetime import datetime, date
    from decimal import Decimal

    task = Task.get_by_id(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    # Serialize datetime/date/Decimal values so jsonify doesn't crash
    serialized = {}
    for k, v in task.items():
        if isinstance(v, (datetime, date)):
            serialized[k] = v.isoformat()
        elif isinstance(v, Decimal):
            serialized[k] = float(v)
        else:
            serialized[k] = v

    serialized['comments']     = Comment.get_by_task(task_id)
    serialized['activity']     = Task.get_activity(task_id)
    serialized['participants'] = Task.get_participants(task_id)
    serialized['observers']    = Task.get_observers(task_id)
    return jsonify(serialized), 200


@task_bp.route('/tasks/<int:task_id>', methods=['PUT'])
@jwt_required()
def update_task(task_id):
    data = request.json
    user_id = int(get_jwt_identity())
    claims = get_jwt()

    task = Task.get_by_id(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    # Employees/developers/smm can only update status on assigned or participant tasks
    if claims['role'] not in LEAD_ROLES and claims['role'] != 'admin':
        participants = Task.get_participants(task_id)
        observers    = Task.get_observers(task_id)
        participant_ids = [p['id'] for p in participants]
        observer_ids    = [o['id'] for o in observers]
        if task['assigned_to'] != user_id and user_id not in participant_ids and user_id not in observer_ids:
            return jsonify({"error": "Unauthorized"}), 403
        # Observers can only view — not update
        if user_id in observer_ids and task['assigned_to'] != user_id and user_id not in participant_ids:
            return jsonify({"error": "Observers cannot update tasks"}), 403
        allowed = {'status', 'time_spent'}
        data = {k: v for k, v in data.items() if k in allowed}

    try:
        allowed_fields = {'title', 'description', 'assigned_to', 'team_id', 'department_id',
                          'status', 'priority', 'due_date', 'time_spent', 'department'}
        update_data = {k: v for k, v in data.items() if k in allowed_fields and v is not None}

        if 'assigned_to' in update_data:
            update_data['assigned_to'] = int(update_data['assigned_to']) if update_data['assigned_to'] else None

        Task.update(task_id, updated_by=user_id, **update_data)

        # REWARD LOGIC: AUTOMATIC GOLD COINS on task completion
        if data.get('status') == 'completed' and task.get('assigned_to'):
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)

            # Fetch dynamic rules from DB
            cursor.execute("SELECT rule_key, coins FROM coin_rules WHERE is_active = 1")
            rules = {r['rule_key']: r['coins'] for r in cursor.fetchall()}

            base_coins = rules.get('task_completed', 20)
            bonus_coins = rules.get('task_on_time', 30)

            amount = base_coins
            reason = f"Completed task: {task['title']}"

            # Timing bonus
            current_date = datetime.now()
            due_date = None
            if task.get('due_date'):
                try: due_date = datetime.strptime(str(task['due_date']), '%Y-%m-%d %H:%M:%S')
                except:
                    try: due_date = datetime.strptime(str(task['due_date']), '%Y-%m-%d')
                    except: pass

            if due_date and current_date <= due_date:
                amount += bonus_coins
                reason = f"Completed task on time: {task['title']}"

            cursor2 = conn.cursor()
            cursor2.execute("INSERT INTO user_rewards (user_id, amount, reason) VALUES (%s, %s, %s)",
                           (task['assigned_to'], amount, reason))
            conn.commit()
            cursor.close(); cursor2.close(); conn.close()

        return jsonify({"message": "Task updated"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@task_bp.route('/tasks/<int:task_id>', methods=['DELETE'])
@jwt_required()
def delete_task(task_id):
    claims = get_jwt()
    if claims['role'] != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    conn = __import__('app.utils.database', fromlist=['get_db_connection']).get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"message": "Task deleted"}), 200


@task_bp.route('/tasks/<int:task_id>/comments', methods=['POST'])
@jwt_required()
def add_comment(task_id):
    data = request.json
    user_id = int(get_jwt_identity())
    try:
        Comment.create(task_id, user_id, data['comment'])
        # Log activity
        from app.utils.database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO task_activity (task_id, user_id, action) VALUES (%s, %s, 'commented')", (task_id, user_id))
        conn.commit()
        cursor.close(); conn.close()
        return jsonify({"message": "Comment added"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@task_bp.route('/clients/<int:client_id>/stats', methods=['GET'])
@jwt_required()
def get_client_stats(client_id):
    stats = Task.get_stats_by_client(client_id)
    total = sum(s['total'] for s in stats)
    completed = sum(s['completed'] for s in stats)
    percentage = (completed / total * 100) if total > 0 else 0
    return jsonify({
        "total_tasks": total,
        "completed_tasks": completed,
        "percentage": round(percentage, 2),
        "by_department": stats
    }), 200


@task_bp.route('/tasks/<int:task_id>/messages', methods=['GET'])
@jwt_required()
def get_task_messages(task_id):
    messages = Task.get_messages(task_id)
    return jsonify(messages), 200


@task_bp.route('/tasks/<int:task_id>/messages', methods=['POST'])
@jwt_required()
def send_task_message(task_id):
    user_id = int(get_jwt_identity())
    data = request.json
    try:
        msg_id = Task.send_message(
            task_id=task_id,
            user_id=user_id,
            content=data['content'],
            message_type=data.get('message_type', 'text'),
            file_url=data.get('file_url')
        )
        return jsonify({"message": "Message sent", "id": msg_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@task_bp.route('/tasks/<int:task_id>/participants', methods=['POST'])
@jwt_required()
def add_participant(task_id):
    data = request.json
    try:
        Task.add_participant(task_id, int(data['user_id']))
        return jsonify({"message": "Participant added"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@task_bp.route('/tasks/<int:task_id>/observers', methods=['POST'])
@jwt_required()
def add_observer(task_id):
    data = request.json
    try:
        Task.add_observer(task_id, int(data['user_id']))
        return jsonify({"message": "Observer added"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@task_bp.route('/tasks/<int:task_id>/participants/<int:user_id>', methods=['DELETE'])
@jwt_required()
def remove_participant(task_id, user_id):
    claims = get_jwt()
    if claims['role'] not in LEAD_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    try:
        Task.remove_participant(task_id, user_id)
        return jsonify({"message": "Participant removed"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@task_bp.route('/tasks/<int:task_id>/observers/<int:user_id>', methods=['DELETE'])
@jwt_required()
def remove_observer(task_id, user_id):
    claims = get_jwt()
    if claims['role'] not in LEAD_ROLES:
        return jsonify({"error": "Unauthorized"}), 403
    try:
        Task.remove_observer(task_id, user_id)
        return jsonify({"message": "Observer removed"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
