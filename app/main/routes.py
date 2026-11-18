# Main blueprint routes
from flask import Blueprint, abort, current_app, jsonify, render_template, request
from flask_login import current_user, login_required
from .. import db
from ..models import Project, Sprint, Task, TeamMember
from .dashboard_data import build_dashboard_data
from ..management.risk_analysis import build_risk_alerts

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def dashboard():
    project_id = _dashboard_filter_id("project_id")
    sprint_id = _dashboard_filter_id("sprint_id")

    projects = Project.query.order_by(Project.name).all()
    selected_project = db.session.get(Project, project_id) if project_id else None
    selected_sprint = db.session.get(Sprint, sprint_id) if sprint_id else None
    if project_id and selected_project is None:
        abort(404)
    if sprint_id and selected_sprint is None:
        abort(404)
    if selected_sprint and selected_project and selected_sprint.project_id != selected_project.id:
        abort(400, description="The selected sprint does not belong to the selected project.")
    if selected_sprint and selected_project is None:
        selected_project = selected_sprint.project

    sprint_query = Sprint.query.order_by(Sprint.start_date, Sprint.name)
    if selected_project:
        sprint_query = sprint_query.filter_by(project_id=selected_project.id)
    if selected_sprint:
        sprint_query = sprint_query.filter_by(id=selected_sprint.id)
    sprints = sprint_query.all()
    tasks = (
        Task.query.filter(Task.sprint_id.in_([sprint.id for sprint in sprints]))
        .order_by(Task.id)
        .all()
        if sprints
        else []
    )
    members = TeamMember.query.order_by(TeamMember.name).all()
    dashboard_data = build_dashboard_data(
        [selected_project] if selected_project else projects,
        sprints,
        tasks,
        members,
        underutilized_threshold=current_app.config[
            "ALLOCATION_UNDERUTILIZED_THRESHOLD"
        ],
        overload_threshold=current_app.config["ALLOCATION_OVERLOAD_THRESHOLD"],
    )
    risk_summary = None
    if current_user.role in {"administrator", "project_manager"}:
        visible_project_ids = {
            project.id
            for project in projects
            if current_user.role == "administrator"
            or project.owner_id == current_user.id
        }
        visible_sprints = [
            sprint for sprint in sprints if sprint.project_id in visible_project_ids
        ]
        visible_sprint_ids = {sprint.id for sprint in visible_sprints}
        visible_tasks = [
            task for task in tasks if task.sprint_id in visible_sprint_ids
        ]
        risk_alerts = build_risk_alerts(
            visible_sprints,
            visible_tasks,
            members,
            settings=current_app.config,
        )
        risk_summary = {
            "total": len(risk_alerts),
            "high": sum(alert["severity"] == "HIGH" for alert in risk_alerts),
            "medium": sum(alert["severity"] == "MEDIUM" for alert in risk_alerts),
            "low": sum(alert["severity"] == "LOW" for alert in risk_alerts),
        }
    return render_template(
        "dashboard.html",
        projects=projects,
        filter_sprints=(
            Sprint.query.filter_by(project_id=selected_project.id)
            .order_by(Sprint.start_date, Sprint.name)
            .all()
            if selected_project
            else Sprint.query.order_by(Sprint.start_date, Sprint.name).all()
        ),
        selected_project_id=selected_project.id if selected_project else None,
        selected_sprint_id=selected_sprint.id if selected_sprint else None,
        overload_threshold=current_app.config["ALLOCATION_OVERLOAD_THRESHOLD"],
        underutilized_threshold=current_app.config[
            "ALLOCATION_UNDERUTILIZED_THRESHOLD"
        ],
        risk_summary=risk_summary,
        **dashboard_data,
    )


def _dashboard_filter_id(name):
    value = request.args.get(name)
    if value in (None, ""):
        return None
    try:
        filter_id = int(value)
    except ValueError:
        abort(400, description=f"Invalid {name} filter.")
    if filter_id <= 0:
        abort(400, description=f"Invalid {name} filter.")
    return filter_id


@main_bp.route('/health')
def health_check():
    """Simple health check endpoint returning JSON status."""
    return jsonify({"status": "ok"})
