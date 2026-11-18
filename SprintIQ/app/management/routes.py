from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from .. import db
from ..models import Project, Sprint, Task, TaskAssignment, TeamMember, User
from .forms import ProjectForm, SprintForm, TaskForm, TeamMemberForm


management_bp = Blueprint("management", __name__)
TASK_STATUSES = (("todo", "To Do"), ("in_progress", "In Progress"), ("done", "Done"))


def management_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role not in {"administrator", "project_manager"}:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def can_manage_project(project):
    return current_user.role == "administrator" or (
        current_user.role == "project_manager" and project.owner_id == current_user.id
    )


def get_project_or_404(project_id):
    project = db.session.get(Project, project_id)
    if project is None:
        abort(404)
    return project


def get_sprint_or_404(sprint_id):
    sprint = db.session.get(Sprint, sprint_id)
    if sprint is None:
        abort(404)
    return sprint


def get_task_or_404(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    return task


def check_project_permission(project):
    if not can_manage_project(project):
        abort(403)


def populate_task_choices(form, projects, members):
    form.sprint_id.choices = {
        str(sprint.id): f"{sprint.project.name} / {sprint.name}"
        for project in projects
        for sprint in project.sprints
    }
    form.team_member_ids.choices = {
        member.id: f"{member.name} ({member.email})" if member.email else member.name
        for member in members
    }


def reconcile_assignments(task, team_member_ids, assigned_hours):
    assignments = {assignment.team_member_id: assignment for assignment in task.assignments}
    selected_ids = set(team_member_ids)
    for member_id, assignment in assignments.items():
        if member_id not in selected_ids:
            task.assignments.remove(assignment)
            db.session.delete(assignment)

    for member_id in selected_ids:
        assignment = assignments.get(member_id)
        if assignment is None:
            assignment = TaskAssignment(
                team_member_id=member_id,
                assigned_hours=assigned_hours or 0,
            )
            task.assignments.append(assignment)
        else:
            assignment.assigned_hours = assigned_hours or 0


def populate_task(task, form, sprint):
    task.sprint = sprint
    task.title = form.title.data.strip()
    task.description = form.description.data
    task.priority = form.priority.data
    task.estimated_hours = form.estimated_hours.data
    task.status = form.status.data
    task.due_date = form.due_date.data


def can_change_task_status(task):
    return can_manage_project(task.sprint.project) or any(
        assignment.team_member.user_id == current_user.id
        for assignment in task.assignments
    )


@management_bp.route("/projects")
@login_required
def projects():
    project_list = Project.query.order_by(Project.created_at.desc(), Project.name).all()
    return render_template(
        "management/projects.html",
        projects=project_list,
        can_create=current_user.role in {"administrator", "project_manager"},
        can_manage=can_manage_project,
    )


@management_bp.route("/sprints")
@login_required
def sprints():
    sprint_list = Sprint.query.join(Project).order_by(
        Project.name, Sprint.start_date
    ).all()
    return render_template("management/sprints.html", sprints=sprint_list)


@management_bp.route("/projects/new", methods=["GET", "POST"])
@management_required
def create_project():
    form = ProjectForm()
    if form.validate_on_submit():
        if form.start_date.data and form.end_date.data and form.end_date.data < form.start_date.data:
            form.end_date.errors.append("End date must be on or after the start date.")
        else:
            project = Project(
                owner_id=current_user.id,
                name=form.name.data.strip(),
                description=form.description.data,
                start_date=form.start_date.data,
                end_date=form.end_date.data,
                status=form.status.data,
            )
            db.session.add(project)
            db.session.commit()
            flash("Project created.", "success")
            return redirect(url_for("management.project_detail", project_id=project.id))
    return render_template(
        "management/form.html",
        title="Create project",
        form=form,
        back_url=url_for("management.projects"),
    )


@management_bp.route("/projects/<int:project_id>")
@login_required
def project_detail(project_id):
    project = get_project_or_404(project_id)
    return render_template(
        "management/project_detail.html",
        project=project,
        can_manage=can_manage_project(project),
    )


@management_bp.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
@management_required
def edit_project(project_id):
    project = get_project_or_404(project_id)
    check_project_permission(project)
    form = ProjectForm(obj=project)
    if form.validate_on_submit():
        if form.start_date.data and form.end_date.data and form.end_date.data < form.start_date.data:
            form.end_date.errors.append("End date must be on or after the start date.")
        else:
            project.name = form.name.data.strip()
            project.description = form.description.data
            project.start_date = form.start_date.data
            project.end_date = form.end_date.data
            project.status = form.status.data
            db.session.commit()
            flash("Project updated.", "success")
            return redirect(url_for("management.project_detail", project_id=project.id))
    return render_template(
        "management/form.html",
        title="Edit project",
        form=form,
        back_url=url_for("management.project_detail", project_id=project.id),
    )


@management_bp.route("/projects/<int:project_id>/delete", methods=["POST"])
@management_required
def delete_project(project_id):
    project = get_project_or_404(project_id)
    check_project_permission(project)
    db.session.delete(project)
    db.session.commit()
    flash("Project and its sprints and tasks were deleted.", "success")
    return redirect(url_for("management.projects"))


@management_bp.route("/projects/<int:project_id>/sprints/new", methods=["GET", "POST"])
@management_required
def create_sprint(project_id):
    project = get_project_or_404(project_id)
    check_project_permission(project)
    form = SprintForm()
    if form.validate_on_submit():
        if form.end_date.data < form.start_date.data:
            form.end_date.errors.append("End date must be on or after the start date.")
        elif project.start_date and form.start_date.data < project.start_date:
            form.start_date.errors.append("Sprint must start within the project dates.")
        elif project.end_date and form.end_date.data > project.end_date:
            form.end_date.errors.append("Sprint must end within the project dates.")
        else:
            sprint = Sprint(
                project=project,
                name=form.name.data.strip(),
                sprint_goal=form.sprint_goal.data,
                start_date=form.start_date.data,
                end_date=form.end_date.data,
                status=form.status.data,
            )
            db.session.add(sprint)
            db.session.commit()
            flash("Sprint created.", "success")
            return redirect(
                url_for("management.project_detail", project_id=project.id)
            )
    return render_template(
        "management/form.html",
        title=f"Create sprint — {project.name}",
        form=form,
        back_url=url_for("management.project_detail", project_id=project.id),
    )


@management_bp.route("/sprints/<int:sprint_id>/edit", methods=["GET", "POST"])
@management_required
def edit_sprint(sprint_id):
    sprint = get_sprint_or_404(sprint_id)
    check_project_permission(sprint.project)
    form = SprintForm(obj=sprint)
    if form.validate_on_submit():
        if form.end_date.data < form.start_date.data:
            form.end_date.errors.append("End date must be on or after the start date.")
        elif sprint.project.start_date and form.start_date.data < sprint.project.start_date:
            form.start_date.errors.append("Sprint must start within the project dates.")
        elif sprint.project.end_date and form.end_date.data > sprint.project.end_date:
            form.end_date.errors.append("Sprint must end within the project dates.")
        else:
            sprint.name = form.name.data.strip()
            sprint.sprint_goal = form.sprint_goal.data
            sprint.start_date = form.start_date.data
            sprint.end_date = form.end_date.data
            sprint.status = form.status.data
            db.session.commit()
            flash("Sprint updated.", "success")
            return redirect(
                url_for("management.project_detail", project_id=sprint.project_id)
            )
    return render_template(
        "management/form.html",
        title=f"Edit sprint — {sprint.project.name}",
        form=form,
        back_url=url_for(
            "management.project_detail", project_id=sprint.project_id
        ),
    )


@management_bp.route("/sprints/<int:sprint_id>/delete", methods=["POST"])
@management_required
def delete_sprint(sprint_id):
    sprint = get_sprint_or_404(sprint_id)
    check_project_permission(sprint.project)
    project_id = sprint.project_id
    db.session.delete(sprint)
    db.session.commit()
    flash("Sprint and its tasks were deleted.", "success")
    return redirect(url_for("management.project_detail", project_id=project_id))


@management_bp.route("/team")
@management_required
def team_members():
    members = TeamMember.query.order_by(TeamMember.name).all()
    return render_template("management/team.html", members=members)


@management_bp.route("/team/new", methods=["GET", "POST"])
@management_required
def create_team_member():
    form = TeamMemberForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        linked_user = User.query.filter_by(email=email).first()
        if linked_user and linked_user.team_member:
            form.email.errors.append("This account is already linked to a team member.")
        else:
            member = TeamMember(
                name=form.name.data.strip(),
                email=email,
                skills=form.skills.data or "",
                available_hours=form.available_hours.data,
                daily_capacity=form.daily_capacity.data,
                user=linked_user,
            )
            db.session.add(member)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.email.errors.append("A team member with this email already exists.")
            else:
                flash("Team member added.", "success")
                return redirect(url_for("management.team_members"))
    return render_template(
        "management/form.html",
        title="Add team member",
        form=form,
        back_url=url_for("management.team_members"),
    )


@management_bp.route("/team/<int:member_id>/edit", methods=["GET", "POST"])
@management_required
def edit_team_member(member_id):
    member = db.get_or_404(TeamMember, member_id)
    form = TeamMemberForm(obj=member)
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        linked_user = User.query.filter_by(email=email).first()
        if linked_user and linked_user.team_member and linked_user.team_member.id != member.id:
            form.email.errors.append("This account is already linked to another team member.")
        else:
            member.name = form.name.data.strip()
            member.email = email
            member.skills = form.skills.data or ""
            member.available_hours = form.available_hours.data
            member.daily_capacity = form.daily_capacity.data
            member.user = linked_user
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.email.errors.append("A team member with this email already exists.")
            else:
                flash("Team member updated.", "success")
                return redirect(url_for("management.team_members"))
    return render_template(
        "management/form.html",
        title="Edit team member",
        form=form,
        back_url=url_for("management.team_members"),
    )


@management_bp.route("/team/<int:member_id>/delete", methods=["POST"])
@management_required
def delete_team_member(member_id):
    member = db.get_or_404(TeamMember, member_id)
    db.session.delete(member)
    db.session.commit()
    flash("Team member and their task assignments were removed.", "success")
    return redirect(url_for("management.team_members"))


@management_bp.route("/tasks")
@login_required
def tasks():
    task_list = Task.query.join(Sprint).join(Project).order_by(
        Project.name, Sprint.start_date, Task.id
    ).all()
    return render_template(
        "management/kanban.html",
        tasks=task_list,
        statuses=TASK_STATUSES,
        can_manage_task=can_manage_project,
        can_change_status=can_change_task_status,
    )


@management_bp.route("/tasks/new", methods=["GET", "POST"])
@management_required
def create_task():
    projects = [
        project
        for project in Project.query.order_by(Project.name).all()
        if can_manage_project(project)
    ]
    members = TeamMember.query.order_by(TeamMember.name).all()
    form = TaskForm()
    populate_task_choices(form, projects, members)
    if form.validate_on_submit():
        sprint = db.session.get(Sprint, int(form.sprint_id.data))
        if sprint is None or not can_manage_project(sprint.project):
            abort(403)
        if form.due_date.data and not (
            sprint.start_date <= form.due_date.data <= sprint.end_date
        ):
            form.due_date.errors.append("Deadline must fall within the selected sprint.")
        else:
            task = Task()
            populate_task(task, form, sprint)
            db.session.add(task)
            db.session.flush()
            reconcile_assignments(
                task, form.team_member_ids.data, form.assigned_hours.data
            )
            db.session.commit()
            flash("Task created.", "success")
            return redirect(url_for("management.tasks"))
    return render_template(
        "management/form.html",
        title="Create task",
        form=form,
        back_url=url_for("management.tasks"),
    )


@management_bp.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
@management_required
def edit_task(task_id):
    task = get_task_or_404(task_id)
    check_project_permission(task.sprint.project)
    projects = [
        project
        for project in Project.query.order_by(Project.name).all()
        if can_manage_project(project)
    ]
    members = TeamMember.query.order_by(TeamMember.name).all()
    form = TaskForm(obj=task)
    populate_task_choices(form, projects, members)
    if request.method == "GET":
        form.team_member_ids.data = [
            assignment.team_member_id for assignment in task.assignments
        ]
        if task.assignments:
            form.assigned_hours.data = task.assignments[0].assigned_hours
    if form.validate_on_submit():
        sprint = db.session.get(Sprint, int(form.sprint_id.data))
        if sprint is None or not can_manage_project(sprint.project):
            abort(403)
        if form.due_date.data and not (
            sprint.start_date <= form.due_date.data <= sprint.end_date
        ):
            form.due_date.errors.append("Deadline must fall within the selected sprint.")
        else:
            populate_task(task, form, sprint)
            reconcile_assignments(
                task, form.team_member_ids.data, form.assigned_hours.data
            )
            db.session.commit()
            flash("Task updated.", "success")
            return redirect(url_for("management.tasks"))
    return render_template(
        "management/form.html",
        title="Edit task",
        form=form,
        back_url=url_for("management.tasks"),
    )


@management_bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
@management_required
def delete_task(task_id):
    task = get_task_or_404(task_id)
    check_project_permission(task.sprint.project)
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted.", "success")
    return redirect(url_for("management.tasks"))


@management_bp.route("/tasks/<int:task_id>/status", methods=["POST"])
@login_required
def update_task_status(task_id):
    task = get_task_or_404(task_id)
    status = request.form.get("status", "")
    if status not in {value for value, _label in TASK_STATUSES}:
        flash("Choose a valid task status.", "danger")
        return redirect(url_for("management.tasks"))

    if not can_change_task_status(task):
        abort(403)

    task.status = status
    db.session.commit()
    flash("Task status updated.", "success")
    return redirect(url_for("management.tasks"))
