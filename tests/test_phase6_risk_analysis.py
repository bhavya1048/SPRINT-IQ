from datetime import date

import pytest

from app import create_app, db
from app.management.risk_analysis import build_risk_alerts
from app.models import Project, Sprint, Task, TaskAssignment, TeamMember, User


AS_OF = date(2026, 11, 18)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase6-test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'phase6.db'}",
        }
    )
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def add_user(app, username, role="project_manager"):
    with app.app_context():
        user = User(
            username=username,
            email=f"{username}@example.com",
            role=role,
        )
        user.set_password("phase6-password")
        db.session.add(user)
        db.session.commit()
        return user.id


def sign_in(client, username):
    return client.post(
        "/auth/login",
        data={
            "email": f"{username}@example.com",
            "password": "phase6-password",
        },
        follow_redirects=True,
    )


def create_scope(
    app,
    owner_id,
    project_name="Risk project",
    sprint_name="Risk sprint",
    sprint_start=date(2026, 11, 2),
    sprint_end=date(2026, 11, 30),
    sprint_status="active",
):
    with app.app_context():
        project = Project(
            owner_id=owner_id,
            name=project_name,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 30),
            status="active",
        )
        sprint = Sprint(
            project=project,
            name=sprint_name,
            start_date=sprint_start,
            end_date=sprint_end,
            status=sprint_status,
        )
        db.session.add_all([project, sprint])
        db.session.commit()
        return project.id, sprint.id


def create_member(
    app,
    name="Developer",
    skills="Python",
    available_hours=80,
    daily_capacity=8,
):
    with app.app_context():
        member = TeamMember(
            name=name,
            email=f"{name.lower().replace(' ', '.')}@example.com",
            skills=skills,
            available_hours=available_hours,
            daily_capacity=daily_capacity,
        )
        db.session.add(member)
        db.session.commit()
        return member.id


def create_task(
    app,
    sprint_id,
    title="Risk task",
    due_date=None,
    priority="medium",
    effort=4,
    status="todo",
    required_skills="Python",
    assignees=(),
):
    with app.app_context():
        task = Task(
            sprint_id=sprint_id,
            title=title,
            due_date=due_date,
            priority=priority,
            estimated_hours=effort,
            status=status,
            required_skills=required_skills,
        )
        db.session.add(task)
        db.session.flush()
        for member_id, hours in assignees:
            db.session.add(
                TaskAssignment(
                    task_id=task.id,
                    team_member_id=member_id,
                    assigned_hours=hours,
                )
            )
        db.session.commit()
        return task.id


def get_alerts(app, as_of=AS_OF, settings=None):
    with app.app_context():
        sprints = Sprint.query.order_by(Sprint.id).all()
        tasks = Task.query.order_by(Task.id).all()
        members = TeamMember.query.order_by(TeamMember.id).all()
        return build_risk_alerts(sprints, tasks, members, as_of, settings)


def alerts_of_type(alerts, risk_type):
    return [alert for alert in alerts if alert["risk_type"] == risk_type]


def test_overdue_and_approaching_deadline_detectors(app):
    owner_id = add_user(app, "deadline-manager")
    _project_id, sprint_id = create_scope(app, owner_id)
    create_member(app)
    overdue_id = create_task(
        app,
        sprint_id,
        title="Overdue",
        due_date=date(2026, 11, 10),
        priority="critical",
    )
    approaching_id = create_task(
        app,
        sprint_id,
        title="Approaching",
        due_date=date(2026, 11, 21),
        priority="high",
    )

    alerts = get_alerts(app)

    overdue = alerts_of_type(alerts, "overdue_task")
    approaching = alerts_of_type(alerts, "deadline_approaching")
    assert len(overdue) == 1
    assert overdue[0]["task_id"] == overdue_id
    assert overdue[0]["severity"] == "HIGH"
    assert "8 day(s) overdue" in overdue[0]["description"]
    assert len(approaching) == 1
    assert approaching[0]["task_id"] == approaching_id
    assert approaching[0]["severity"] == "MEDIUM"


def test_deadline_boundary_conditions_and_priority_scope(app):
    owner_id = add_user(app, "boundary-manager")
    _project_id, sprint_id = create_scope(app, owner_id)
    create_member(app)
    for title, due, priority in (
        ("Due yesterday", date(2026, 11, 17), "high"),
        ("Due today", AS_OF, "high"),
        ("Due in one", date(2026, 11, 19), "critical"),
        ("Due in three", date(2026, 11, 21), "high"),
        ("Due at window", date(2026, 11, 23), "high"),
        ("Due outside window", date(2026, 11, 24), "high"),
        ("Low priority", date(2026, 11, 19), "low"),
    ):
        create_task(
            app,
            sprint_id,
            title=title,
            due_date=due,
            priority=priority,
        )

    alerts = get_alerts(app)

    overdue = alerts_of_type(alerts, "overdue_task")
    approaching = alerts_of_type(alerts, "deadline_approaching")
    assert [(alert["description"], alert["severity"]) for alert in overdue] == [
        ("Due yesterday is 1 day(s) overdue.", "LOW")
    ]
    assert {alert["task"].title: alert["severity"] for alert in approaching} == {
        "Due today": "HIGH",
        "Due in one": "HIGH",
        "Due in three": "MEDIUM",
        "Due at window": "LOW",
    }


def test_overloaded_member_detector_uses_phase4_capacity(app):
    owner_id = add_user(app, "overload-manager")
    _project_id, sprint_id = create_scope(
        app,
        owner_id,
        sprint_start=date(2026, 11, 16),
        sprint_end=date(2026, 11, 20),
    )
    member_id = create_member(
        app,
        available_hours=5,
        daily_capacity=1,
    )
    task_id = create_task(
        app,
        sprint_id,
        title="Over capacity",
        effort=7,
        status="done",
        assignees=[(member_id, 7)],
    )

    alerts = get_alerts(app)
    overloaded = alerts_of_type(alerts, "overloaded_member")

    assert len(overloaded) == 1
    assert overloaded[0]["team_member"].name == "Developer"
    assert overloaded[0]["task"] is None
    assert overloaded[0]["severity"] == "HIGH"
    assert "7.0h is allocated against 5.0h available" in overloaded[0]["reason"]
    assert task_id not in {alert["task_id"] for alert in overloaded}


def test_overload_severity_levels_are_configurable(app):
    owner_id = add_user(app, "overload-level-manager")
    _project_id, sprint_id = create_scope(
        app,
        owner_id,
        sprint_start=date(2026, 11, 16),
        sprint_end=date(2026, 11, 20),
    )
    for name, assigned_hours in (
        ("Low Overload", 105),
        ("Medium Overload", 115),
        ("High Overload", 130),
    ):
        member_id = create_member(
            app,
            name=name,
            skills="Python",
            available_hours=100,
            daily_capacity=20,
        )
        create_task(
            app,
            sprint_id,
            title=f"Task for {name}",
            effort=assigned_hours,
            status="done",
            assignees=[(member_id, assigned_hours)],
        )

    alerts = get_alerts(app)
    overload_by_member = {
        alert["team_member"].name: alert["severity"]
        for alert in alerts_of_type(alerts, "overloaded_member")
    }

    assert overload_by_member == {
        "Low Overload": "LOW",
        "Medium Overload": "MEDIUM",
        "High Overload": "HIGH",
    }


def test_sprint_completion_risk_compares_remaining_effort_to_capacity(app):
    owner_id = add_user(app, "sprint-risk-manager")
    _project_id, sprint_id = create_scope(
        app,
        owner_id,
        sprint_start=date(2026, 11, 2),
        sprint_end=date(2026, 11, 21),
    )
    create_member(app, available_hours=10, daily_capacity=2)
    task_id = create_task(
        app,
        sprint_id,
        title="Large remaining task",
        effort=9,
    )

    alerts = get_alerts(app)
    sprint_risks = alerts_of_type(alerts, "sprint_completion")

    assert len(sprint_risks) == 1
    assert sprint_risks[0]["task_id"] == task_id
    assert sprint_risks[0]["severity"] == "MEDIUM"
    assert "9.0h remains with 10.0h available" in sprint_risks[0]["reason"]


def test_sprint_completion_window_and_load_severity_thresholds(app):
    owner_id = add_user(app, "sprint-boundary-manager")
    _project_id, sprint_id = create_scope(
        app,
        owner_id,
        sprint_start=date(2026, 11, 2),
        sprint_end=date(2026, 11, 23),
    )
    create_member(app, available_hours=10, daily_capacity=2)
    create_task(app, sprint_id, effort=10)

    alerts = get_alerts(app)

    assert len(alerts_of_type(alerts, "sprint_completion")) == 1
    assert alerts_of_type(alerts, "sprint_completion")[0]["severity"] == "HIGH"


def test_unassigned_and_no_eligible_tasks_are_distinguished(app):
    owner_id = add_user(app, "eligibility-manager")
    _project_id, sprint_id = create_scope(app, owner_id)
    create_member(app, name="Python Developer", skills="Python")
    unassigned_id = create_task(
        app,
        sprint_id,
        title="Eligible but unassigned",
        required_skills="Python",
    )
    no_eligible_id = create_task(
        app,
        sprint_id,
        title="No eligible member",
        required_skills="Rust",
    )

    alerts = get_alerts(app)
    unassigned = alerts_of_type(alerts, "unassigned_task")
    no_eligible = alerts_of_type(alerts, "no_eligible_assignee")

    assert [alert["task_id"] for alert in unassigned] == [unassigned_id]
    assert [alert["task_id"] for alert in no_eligible] == [no_eligible_id]
    assert "1 team member(s)" in unassigned[0]["reason"]
    assert "no team member currently meets" in no_eligible[0]["reason"]


def test_assigned_task_with_only_ineligible_assignees_is_flagged_once(app):
    owner_id = add_user(app, "unsuitable-manager")
    _project_id, sprint_id = create_scope(app, owner_id)
    first_id = create_member(app, name="No Python One", skills="Design")
    second_id = create_member(app, name="No Python Two", skills="Writing")
    task_id = create_task(
        app,
        sprint_id,
        title="Unsuitable assignment",
        required_skills="Python",
        assignees=[(first_id, 2), (second_id, 2)],
    )

    alerts = get_alerts(app)
    unsuitable = alerts_of_type(alerts, "unsuitable_assignment")

    assert len(unsuitable) == 1
    assert unsuitable[0]["task_id"] == task_id
    assert "No required skills match." in unsuitable[0]["reason"]


def test_duplicate_alerts_are_not_generated_for_same_task(app):
    owner_id = add_user(app, "duplicate-risk-manager")
    _project_id, sprint_id = create_scope(app, owner_id)
    for number in range(3):
        create_member(app, name=f"No Match {number}", skills="Design")
    task_id = create_task(
        app,
        sprint_id,
        title="Unassignable task",
        required_skills="Python",
    )

    alerts = get_alerts(app)
    task_alerts = [alert for alert in alerts if alert["task_id"] == task_id]

    assert len(alerts_of_type(task_alerts, "no_eligible_assignee")) == 1
    assert len(alerts_of_type(task_alerts, "unassigned_task")) == 0


def test_empty_risk_dashboard_and_manager_authorization(app, client):
    assert client.get("/risks").status_code == 302
    add_user(app, "empty-risk-manager")
    sign_in(client, "empty-risk-manager")

    response = client.get("/risks")

    assert response.status_code == 200
    assert b'>0</div><div class="stat-card-label">Active risks' in response.data
    assert b"Showing 0 risk(s)" in response.data
    assert b"No risks match these filters" in response.data

    with app.app_context():
        outsider = User(
            username="outside-manager",
            email="outside-manager@example.com",
            role="project_manager",
        )
        outsider.set_password("phase6-password")
        team_user = User(
            username="risk-team-member",
            email="risk-team-member@example.com",
            role="team_member",
        )
        team_user.set_password("phase6-password")
        db.session.add_all([outsider, team_user])
        db.session.commit()
        project_id, sprint_id = create_scope(app, outsider.id, project_name="Private")

    assert client.get(f"/risks?project_id={project_id}").status_code == 404
    assert client.get(f"/risks?sprint_id={sprint_id}").status_code == 404
    client.post("/auth/logout")
    sign_in(client, "risk-team-member")
    assert client.get("/risks").status_code == 403


def test_risk_dashboard_project_sprint_severity_and_category_filters(app, client):
    manager_id = add_user(app, "filter-risk-manager")
    first_project_id, first_sprint_id = create_scope(
        app, manager_id, project_name="First Risk Project"
    )
    _second_project_id, second_sprint_id = create_scope(
        app,
        manager_id,
        project_name="Second Risk Project",
        sprint_name="Second Risk Sprint",
    )
    create_member(app, name="Filter Developer")
    create_task(
        app,
        first_sprint_id,
        title="Old critical task",
        due_date=date(2026, 11, 9),
        priority="critical",
    )
    create_task(
        app,
        second_sprint_id,
        title="Near high task",
        due_date=date(2026, 11, 19),
        priority="high",
    )
    sign_in(client, "filter-risk-manager")

    all_risks = client.get("/risks")
    assert all_risks.status_code == 200
    assert b"Old critical task" in all_risks.data
    assert b"Near high task" in all_risks.data

    filtered = client.get(
        f"/risks?project_id={first_project_id}&sprint_id={first_sprint_id}"
        "&severity=HIGH&category=deadlines"
    )
    assert filtered.status_code == 200
    assert b"Old critical task" in filtered.data
    assert b"Near high task" not in filtered.data
    assert b"Showing 1 risk(s)" in filtered.data
    assert client.get("/risks?severity=urgent").status_code == 400
    assert client.get("/risks?category=unknown").status_code == 400
    assert client.get(
        f"/risks?project_id={first_project_id}&sprint_id={second_sprint_id}"
    ).status_code == 400


def test_existing_dashboard_shows_risk_summary_only_for_managed_projects(app, client):
    manager_id = add_user(app, "summary-risk-manager")
    outsider_id = add_user(app, "summary-other-manager")
    _managed_project_id, managed_sprint_id = create_scope(
        app, manager_id, project_name="Managed risk project"
    )
    _other_project_id, other_sprint_id = create_scope(
        app, outsider_id, project_name="Other risk project"
    )
    create_member(app, name="Summary Developer")
    create_task(
        app,
        managed_sprint_id,
        title="Managed overdue task",
        due_date=date(2026, 11, 10),
        priority="high",
    )
    create_task(
        app,
        other_sprint_id,
        title="Other overdue task",
        due_date=date(2026, 11, 10),
        priority="high",
    )
    sign_in(client, "summary-risk-manager")

    dashboard = client.get("/")

    assert dashboard.status_code == 200
    assert b"Sprint risk monitor" in dashboard.data
    assert b"2 active risk(s) in your accessible projects" in dashboard.data
    assert b"Other overdue task" not in dashboard.data

    client.post("/auth/logout")
    add_user(app, "summary-team-user", role="team_member")
    sign_in(client, "summary-team-user")
    member_dashboard = client.get("/")
    assert member_dashboard.status_code == 200
    assert b"Sprint risk monitor" not in member_dashboard.data
