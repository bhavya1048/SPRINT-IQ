# Main blueprint routes
from flask import Blueprint, render_template, jsonify
from flask_login import login_required
from ..models import Project, Sprint, Task, TeamMember

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        project_count=Project.query.filter_by(status="active").count(),
        sprint_count=Sprint.query.filter(Sprint.status != "completed").count(),
        completed_task_count=Task.query.filter_by(status="done").count(),
        member_count=TeamMember.query.count(),
    )

@main_bp.route('/health')
def health_check():
    """Simple health check endpoint returning JSON status."""
    return jsonify({"status": "ok"})
