import json
import re
from datetime import date

import pytest

from app import create_app, db
from app.models import Project, Sprint, Task, TaskAssignment, TeamMember, User


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase5-test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'phase5.db'}",
        }
    )
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def create_manager(app):
    with app.app_context():
        manager = User(
            username="phase5-manager",
            email="phase5-manager@example.com",
            role="project_manager",
        )
        manager.set_password("phase5-password")
        db.session.add(manager)
        db.session.commit()
        return manager.id


def sign_in(client):
    return client.post(
        "/auth/login",
        data={
            "email": "phase5-manager@example.com",
            "password": "phase5-password",
        },
        follow_redirects=True,
    )


def create_dashboard_data(app, manager_id):
    with app.app_context():
        manager = db.session.get(User, manager_id)
        first_project = Project(
            owner=manager,
            name="Alpha Project",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            status="active",
        )
        second_project = Project(
            owner=manager,
            name="Beta Project",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            status="active",
        )
        first_sprint = Sprint(
            project=first_project,
            name="Alpha Sprint One",
            start_date=date(2026, 4, 6),
            end_date=date(2026, 4, 10),
            status="active",
        )
        second_sprint = Sprint(
            project=first_project,
            name="Alpha Sprint Two",
            start_date=date(2026, 4, 13),
            end_date=date(2026, 4, 17),
            status="planned",
        )
        other_sprint = Sprint(
            project=second_project,
            name="Beta Sprint",
            start_date=date(2026, 4, 20),
            end_date=date(2026, 4, 24),
            status="planned",
        )
        member = TeamMember(
            name="Alex Developer",
            email="alex-phase5@example.com",
            skills="Python",
            available_hours=40,
            daily_capacity=8,
        )
        done_task = Task(
            sprint=first_sprint,
            title="Completed task",
            priority="high",
            estimated_hours=3,
            status="done",
        )
        todo_task = Task(
            sprint=first_sprint,
            title="Pending task",
            priority="medium",
            estimated_hours=5,
            status="todo",
        )
        progress_task = Task(
            sprint=second_sprint,
            title="In progress task",
            priority="critical",
            estimated_hours=7,
            status="in_progress",
        )
        other_task = Task(
            sprint=other_sprint,
            title="Other project task",
            priority="low",
            estimated_hours=9,
            status="todo",
        )
        db.session.add_all(
            [
                first_project,
                second_project,
                first_sprint,
                second_sprint,
                other_sprint,
                member,
                done_task,
                todo_task,
                progress_task,
                other_task,
            ]
        )
        db.session.flush()
        db.session.add_all(
            [
                TaskAssignment(
                    task=done_task,
                    team_member=member,
                    assigned_hours=2,
                ),
                TaskAssignment(
                    task=todo_task,
                    team_member=member,
                    assigned_hours=6,
                ),
                TaskAssignment(
                    task=progress_task,
                    team_member=member,
                    assigned_hours=4,
                ),
            ]
        )
        db.session.commit()
        return {
            "project_one": first_project.id,
            "project_two": second_project.id,
            "sprint_one": first_sprint.id,
            "sprint_two": second_sprint.id,
        }


def parse_chart_data(response):
    match = re.search(
        rb'<script type="application/json" id="dashboard-chart-data">(.*?)</script>',
        response.data,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def assert_stat(response, stat_id, expected):
    match = re.search(
        rb'data-stat="' + stat_id.encode() + rb'".*?class="stat-card-value">(\d+)</div>',
        response.data,
        re.DOTALL,
    )
    assert match is not None
    assert int(match.group(1)) == expected


def test_dashboard_statistics_charts_progress_and_workload_are_database_backed(
    app, client
):
    manager_id = create_manager(app)
    ids = create_dashboard_data(app, manager_id)
    sign_in(client)

    response = client.get("/")

    assert response.status_code == 200
    for stat_id, count in {
        "projects": 2,
        "sprints": 3,
        "tasks": 4,
        "completed": 1,
        "pending": 2,
        "in-progress": 1,
        "team-members": 1,
    }.items():
        assert_stat(response, stat_id, count)

    data = parse_chart_data(response)
    assert data["status"]["values"] == [2, 1, 1, 0]
    assert data["priority"]["values"] == [1, 1, 1, 1, 0]
    assert data["sprint_progress"]["values"] == [50.0, 0.0, 0.0]
    assert data["workload"]["labels"] == ["Alex Developer"]
    assert data["workload"]["allocated"] == [12.0]
    assert data["workload"]["remaining"] == [108.0]

    with app.app_context():
        assert db.session.get(Sprint, ids["sprint_one"]) is not None
    assert b'data-completion="50.0"' in response.data
    assert b"5.0h" in response.data


def test_project_and_sprint_filters_apply_consistently(app, client):
    manager_id = create_manager(app)
    ids = create_dashboard_data(app, manager_id)
    sign_in(client)

    project_response = client.get(f"/?project_id={ids['project_one']}")
    assert project_response.status_code == 200
    assert_stat(project_response, "projects", 1)
    assert_stat(project_response, "sprints", 2)
    assert_stat(project_response, "tasks", 3)
    project_data = parse_chart_data(project_response)
    assert project_data["status"]["values"] == [1, 1, 1, 0]
    assert project_data["priority"]["values"] == [0, 1, 1, 1, 0]
    assert project_data["workload"]["allocated"] == [12.0]

    sprint_response = client.get(f"/?sprint_id={ids['sprint_two']}")
    assert sprint_response.status_code == 200
    assert_stat(sprint_response, "projects", 1)
    assert_stat(sprint_response, "sprints", 1)
    assert_stat(sprint_response, "tasks", 1)
    sprint_data = parse_chart_data(sprint_response)
    assert sprint_data["status"]["values"] == [0, 1, 0, 0]
    assert sprint_data["workload"]["allocated"] == [4.0]


def test_invalid_or_mismatched_filters_are_rejected(app, client):
    manager_id = create_manager(app)
    ids = create_dashboard_data(app, manager_id)
    sign_in(client)

    assert client.get("/?project_id=not-a-number").status_code == 400
    assert client.get("/?project_id=99999").status_code == 404
    assert client.get(
        f"/?project_id={ids['project_two']}&sprint_id={ids['sprint_one']}"
    ).status_code == 400


def test_empty_dashboard_and_authentication_are_handled(app, client):
    assert client.get("/").status_code == 302
    create_manager(app)
    sign_in(client)

    response = client.get("/")

    assert response.status_code == 200
    for stat_id in (
        "projects",
        "sprints",
        "tasks",
        "completed",
        "pending",
        "in-progress",
        "team-members",
    ):
        assert_stat(response, stat_id, 0)
    data = parse_chart_data(response)
    assert data["status"]["values"] == [0, 0, 0, 0]
    assert data["priority"]["values"] == [0, 0, 0, 0, 0]
    assert data["sprint_progress"]["rows"] == []
    assert data["workload"]["labels"] == []
    assert b"No tasks match the selected filters." in response.data
    assert b"No sprints match the selected filters." in response.data


def test_empty_sprint_progress_is_zero_and_safe(app, client):
    manager_id = create_manager(app)
    with app.app_context():
        project = Project(
            owner_id=manager_id,
            name="Empty sprint project",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        )
        sprint = Sprint(
            project=project,
            name="Empty sprint",
            start_date=date(2026, 4, 6),
            end_date=date(2026, 4, 10),
        )
        db.session.add_all([project, sprint])
        db.session.commit()
        sprint_id = sprint.id
    sign_in(client)

    response = client.get(f"/?sprint_id={sprint_id}")

    assert response.status_code == 200
    assert b'data-completion="0.0"' in response.data
    assert b"0.0%" in response.data
    assert b"0.0h" in response.data
    assert parse_chart_data(response)["sprint_progress"]["values"] == [0.0]


def test_dashboard_marks_overloaded_and_underutilized_members(app, client):
    manager_id = create_manager(app)
    create_dashboard_data(app, manager_id)
    with app.app_context():
        overloaded_member = TeamMember.query.filter_by(
            name="Alex Developer"
        ).one()
        overloaded_member.available_hours = 2
        overloaded_member.daily_capacity = 1
        underutilized_member = TeamMember(
            name="Blair Developer",
            email="blair-phase5@example.com",
            available_hours=40,
            daily_capacity=8,
        )
        db.session.add(underutilized_member)
        db.session.commit()
    sign_in(client)

    response = client.get("/")

    assert response.status_code == 200
    assert b"Overloaded" in response.data
    assert b"Underutilized" in response.data
    data = parse_chart_data(response)
    assert data["workload"]["labels"] == ["Alex Developer", "Blair Developer"]
    assert data["workload"]["allocated"] == [12.0, 0]
