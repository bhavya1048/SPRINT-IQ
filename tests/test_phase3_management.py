from datetime import date
import re
import sqlite3

import pytest

from app import create_app, db
from app.models import Project, Sprint, Task, TaskAssignment, TeamMember, User


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase3-test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'phase3.db'}",
        }
    )
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def add_user(app, username, role, email=None):
    email = email or f"{username}@example.com"
    with app.app_context():
        user = User(username=username, email=email, role=role)
        user.set_password("phase3-password")
        db.session.add(user)
        db.session.commit()
        return user.id


def sign_in(client, email):
    return client.post(
        "/auth/login",
        data={"email": email, "password": "phase3-password"},
        follow_redirects=True,
    )


def create_project(client, name="Release", **overrides):
    data = {
        "name": name,
        "description": "Phase 3 project",
        "start_date": "2026-01-01",
        "end_date": "2026-03-31",
        "status": "active",
    }
    data.update(overrides)
    return client.post("/projects/new", data=data)


def test_project_crud_ownership_and_cascade(app, client):
    manager_id = add_user(app, "manager", "project_manager")
    sign_in(client, "manager@example.com")

    created = create_project(client)
    assert created.status_code == 302
    with app.app_context():
        project = Project.query.one()
        assert project.owner_id == manager_id
        project_id = project.id

    assert client.get("/projects").status_code == 200
    assert client.get(f"/projects/{project_id}").status_code == 200
    edited = client.post(
        f"/projects/{project_id}/edit",
        data={
            "name": "Release 2",
            "description": "Updated",
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "status": "planning",
        },
    )
    assert edited.status_code == 302

    with app.app_context():
        project = db.session.get(Project, project_id)
        sprint = Sprint(
            project=project,
            name="Sprint",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 16),
        )
        task = Task(sprint=sprint, title="Task")
        db.session.add_all([sprint, task])
        db.session.commit()

    other_manager = add_user(app, "other-manager", "project_manager")
    client.post("/auth/logout")
    sign_in(client, "other-manager@example.com")
    assert client.get(f"/projects/{project_id}/edit").status_code == 403
    client.post("/auth/logout")
    sign_in(client, "manager@example.com")
    assert client.post(f"/projects/{project_id}/delete").status_code == 302
    with app.app_context():
        assert Project.query.count() == 0
        assert Sprint.query.count() == 0
        assert Task.query.count() == 0
    assert other_manager


def test_project_and_sprint_date_validation(client, app):
    add_user(app, "manager", "project_manager")
    sign_in(client, "manager@example.com")

    invalid_project = create_project(
        client, start_date="2026-03-01", end_date="2026-02-01"
    )
    assert invalid_project.status_code == 200
    assert b"End date must be on or after" in invalid_project.data

    create_project(client)
    with app.app_context():
        project_id = Project.query.one().id
    invalid_sprint = client.post(
        f"/projects/{project_id}/sprints/new",
        data={
            "name": "Invalid sprint",
            "sprint_goal": "",
            "start_date": "2026-02-01",
            "end_date": "2026-01-20",
            "status": "planned",
        },
    )
    assert invalid_sprint.status_code == 200
    assert b"End date must be on or after" in invalid_sprint.data

    out_of_project = client.post(
        f"/projects/{project_id}/sprints/new",
        data={
            "name": "Outside project",
            "sprint_goal": "",
            "start_date": "2025-12-20",
            "end_date": "2026-01-10",
            "status": "planned",
        },
    )
    assert b"within the project dates" in out_of_project.data


def test_project_date_changes_cannot_exclude_existing_sprints(app, client):
    add_user(app, "manager", "project_manager")
    sign_in(client, "manager@example.com")
    create_project(client)
    with app.app_context():
        project = Project.query.one()
        project_id = project.id
        sprint = Sprint(
            project=project,
            name="Sprint 1",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 16),
        )
        db.session.add(sprint)
        db.session.commit()

    start_outside_sprint = client.post(
        f"/projects/{project_id}/edit",
        data={
            "name": "Release",
            "description": "Phase 3 project",
            "start_date": "2026-01-10",
            "end_date": "2026-03-31",
            "status": "active",
        },
    )
    assert start_outside_sprint.status_code == 200
    assert b"cannot be after an existing sprint starts" in start_outside_sprint.data
    with app.app_context():
        assert db.session.get(Project, project_id).start_date == date(2026, 1, 1)

    end_outside_sprint = client.post(
        f"/projects/{project_id}/edit",
        data={
            "name": "Release",
            "description": "Phase 3 project",
            "start_date": "2026-01-01",
            "end_date": "2026-01-10",
            "status": "active",
        },
    )
    assert end_outside_sprint.status_code == 200
    assert b"cannot be before an existing sprint ends" in end_outside_sprint.data
    with app.app_context():
        project = db.session.get(Project, project_id)
        assert project.start_date == date(2026, 1, 1)
        assert project.end_date == date(2026, 3, 31)


def test_dashboard_statistics_use_database_counts_and_handle_empty_state(app, client):
    add_user(app, "manager", "project_manager")
    sign_in(client, "manager@example.com")

    empty_dashboard = client.get("/")
    assert empty_dashboard.status_code == 200
    assert re.findall(
        r'class="stat-card-value">(\d+)</div>',
        empty_dashboard.get_data(as_text=True),
    ) == ["0", "0", "0", "0", "0", "0", "0"]
    assert b'href="/projects/new"' in empty_dashboard.data
    assert b'href="/sprints"' in empty_dashboard.data

    with app.app_context():
        active_project = Project(
            name="Active project",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            status="active",
        )
        planning_project = Project(name="Planning project", status="planning")
        planned_sprint = Sprint(
            project=active_project,
            name="Planned sprint",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 16),
            status="planned",
        )
        completed_sprint = Sprint(
            project=active_project,
            name="Completed sprint",
            start_date=date(2026, 1, 19),
            end_date=date(2026, 1, 30),
            status="completed",
        )
        db.session.add_all(
            [
                active_project,
                planning_project,
                planned_sprint,
                completed_sprint,
                Task(sprint=planned_sprint, title="Open task"),
                Task(sprint=completed_sprint, title="Done task", status="done"),
                TeamMember(name="Developer", email="developer@example.com"),
            ]
        )
        db.session.commit()

    populated_dashboard = client.get("/")
    assert populated_dashboard.status_code == 200
    assert re.findall(
        r'class="stat-card-value">(\d+)</div>',
        populated_dashboard.get_data(as_text=True),
    ) == ["2", "2", "2", "1", "1", "0", "1"]


def test_administrator_can_manage_legacy_project_without_owner(app, client):
    add_user(app, "admin", "administrator")
    add_user(app, "manager", "project_manager")
    with app.app_context():
        project = Project(name="Legacy project")
        db.session.add(project)
        db.session.commit()
        project_id = project.id

    sign_in(client, "admin@example.com")
    details = client.get(f"/projects/{project_id}")
    assert details.status_code == 200
    assert b"Unassigned" in details.data
    assert client.get(f"/projects/{project_id}/edit").status_code == 200

    client.post("/auth/logout")
    sign_in(client, "manager@example.com")
    assert client.get(f"/projects/{project_id}/edit").status_code == 403


def test_sprint_crud(client, app):
    add_user(app, "manager", "project_manager")
    sign_in(client, "manager@example.com")
    create_project(client)
    with app.app_context():
        project_id = Project.query.one().id

    created = client.post(
        f"/projects/{project_id}/sprints/new",
        data={
            "name": "Sprint 1",
            "sprint_goal": "Ship the first release",
            "start_date": "2026-01-05",
            "end_date": "2026-01-16",
            "status": "planned",
        },
    )
    assert created.status_code == 302
    with app.app_context():
        sprint_id = Sprint.query.one().id

    assert client.get("/sprints").status_code == 200
    assert client.post(
        f"/sprints/{sprint_id}/edit",
        data={
            "name": "Sprint 1 revised",
            "sprint_goal": "Updated goal",
            "start_date": "2026-01-05",
            "end_date": "2026-01-16",
            "status": "active",
        },
    ).status_code == 302
    assert client.post(f"/sprints/{sprint_id}/delete").status_code == 302
    with app.app_context():
        assert Sprint.query.count() == 0


def test_team_member_crud_duplicate_email_and_capacity_validation(app, client):
    add_user(app, "manager", "project_manager")
    linked_user_id = add_user(app, "developer", "team_member")
    sign_in(client, "manager@example.com")

    data = {
        "name": "Dev One",
        "email": "DEVELOPER@example.com",
        "skills": "Python, SQL",
        "available_hours": "30",
        "daily_capacity": "6",
    }
    assert client.post("/team/new", data=data).status_code == 302
    with app.app_context():
        member = TeamMember.query.one()
        member_id = member.id
        assert member.email == "developer@example.com"
        assert member.user_id == linked_user_id
        assert member.available_hours == 30

    duplicate = client.post("/team/new", data={**data, "name": "Another"})
    assert duplicate.status_code == 200
    assert b"already linked" in duplicate.data
    external_member = {
        **data,
        "name": "Contractor",
        "email": "contractor@example.com",
    }
    assert client.post("/team/new", data=external_member).status_code == 302
    duplicate_external = client.post(
        "/team/new", data={**external_member, "name": "Duplicate contractor"}
    )
    assert duplicate_external.status_code == 200
    assert b"already exists" in duplicate_external.data
    invalid_capacity = client.post(
        "/team/new",
        data={**data, "email": "second@example.com", "available_hours": "-1"},
    )
    assert invalid_capacity.status_code == 200
    assert b"Number must be" in invalid_capacity.data

    assert client.get("/team").status_code == 200
    assert client.post(
        f"/team/{member_id}/edit",
        data={**data, "name": "Dev Updated", "email": "dev-updated@example.com"},
    ).status_code == 302
    assert client.post(f"/team/{member_id}/delete").status_code == 302
    with app.app_context():
        assert TeamMember.query.count() == 1
        assert db.session.get(User, linked_user_id) is not None
        remaining_member_id = TeamMember.query.one().id
    assert client.post(f"/team/{remaining_member_id}/delete").status_code == 302
    with app.app_context():
        assert TeamMember.query.count() == 0


def test_task_crud_assignments_kanban_and_assignee_permissions(app, client):
    manager_id = add_user(app, "manager", "project_manager")
    member_user_id = add_user(app, "developer", "team_member")
    second_member_user_id = add_user(app, "qa", "team_member")
    outsider_user_id = add_user(app, "outsider", "team_member")
    with app.app_context():
        manager = db.session.get(User, manager_id)
        project = Project(
            owner=manager,
            name="Release",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            status="active",
        )
        sprint = Sprint(
            project=project,
            name="Sprint 1",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 16),
        )
        member = TeamMember(
            user_id=member_user_id,
            name="Developer",
            email="developer@example.com",
            available_hours=30,
            daily_capacity=6,
        )
        other_member = TeamMember(
            user_id=second_member_user_id,
            name="Other",
            email="qa@example.com",
            available_hours=20,
            daily_capacity=5,
        )
        outsider = TeamMember(
            user_id=outsider_user_id,
            name="Unassigned",
            email="outsider@example.com",
            available_hours=20,
            daily_capacity=5,
        )
        db.session.add_all([project, sprint, member, other_member, outsider])
        db.session.commit()
        sprint_id = sprint.id
        member_id = member.id
        other_member_id = other_member.id

    sign_in(client, "manager@example.com")
    task_data = {
        "sprint_id": str(sprint_id),
        "title": "Build feature",
        "description": "Feature details",
        "priority": "critical",
        "estimated_hours": "8",
        "status": "todo",
        "due_date": "2026-01-15",
        "team_member_ids": [str(member_id), str(other_member_id)],
        "assigned_hours": "4",
    }
    assert client.post("/tasks/new", data=task_data).status_code == 302
    with app.app_context():
        task = Task.query.one()
        task_id = task.id
        assert task.sprint.id == sprint_id
        assert task.priority == "critical"
        assert {item.team_member_id for item in task.assignments} == {
            member_id,
            other_member_id,
        }
        assert all(item.assigned_hours == 4 for item in task.assignments)

    assert client.get("/tasks").status_code == 200
    updated_data = {**task_data, "title": "Build feature revised", "status": "in_progress"}
    assert client.post(f"/tasks/{task_id}/edit", data=updated_data).status_code == 302
    assert client.post(
        f"/tasks/{task_id}/status", data={"status": "done"}
    ).status_code == 302
    with app.app_context():
        assert db.session.get(Task, task_id).status == "done"

    client.post("/auth/logout")
    sign_in(client, "developer@example.com")
    assert client.post(
        f"/tasks/{task_id}/status", data={"status": "in_progress"}
    ).status_code == 302
    client.post("/auth/logout")
    sign_in(client, "outsider@example.com")
    assert client.post(
        f"/tasks/{task_id}/status", data={"status": "todo"}
    ).status_code == 403
    assert client.post(f"/tasks/{task_id}/delete").status_code == 403

    client.post("/auth/logout")
    sign_in(client, "manager@example.com")
    assert client.post(
        f"/tasks/{task_id}/status", data={"status": "not-a-status"}
    ).status_code == 302
    with app.app_context():
        assert db.session.get(Task, task_id).status == "in_progress"
    assert client.post(f"/tasks/{task_id}/delete").status_code == 302
    with app.app_context():
        assert Task.query.count() == 0
        assert TaskAssignment.query.count() == 0


def test_task_deadline_and_authorization_validation(app, client):
    add_user(app, "manager", "project_manager")
    add_user(app, "other-manager", "project_manager")
    sign_in(client, "manager@example.com")
    create_project(client)
    with app.app_context():
        project = Project.query.one()
        project_id = project.id
        sprint = Sprint(
            project=project,
            name="Sprint 1",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 16),
        )
        db.session.add(sprint)
        db.session.commit()
        sprint_id = sprint.id

    response = client.post(
        "/tasks/new",
        data={
            "sprint_id": str(sprint_id),
            "title": "Late task",
            "description": "",
            "priority": "medium",
            "estimated_hours": "1",
            "status": "todo",
            "due_date": "2026-01-20",
            "team_member_ids": [],
            "assigned_hours": "0",
        },
    )
    assert response.status_code == 200
    assert b"Deadline must fall within" in response.data
    invalid_priority = client.post(
        "/tasks/new",
        data={
            "sprint_id": str(sprint_id),
            "title": "Bad priority",
            "description": "",
            "priority": "urgent",
            "estimated_hours": "1",
            "status": "todo",
            "due_date": "2026-01-10",
            "team_member_ids": [],
            "assigned_hours": "0",
        },
    )
    assert invalid_priority.status_code == 200
    assert b"Not a valid choice" in invalid_priority.data
    invalid_assignee = client.post(
        "/tasks/new",
        data={
            "sprint_id": str(sprint_id),
            "title": "Invalid assignee",
            "description": "",
            "priority": "medium",
            "estimated_hours": "1",
            "status": "todo",
            "due_date": "2026-01-10",
            "team_member_ids": ["99999"],
            "assigned_hours": "0",
        },
    )
    assert invalid_assignee.status_code == 200
    assert b"not a valid choice for this field" in invalid_assignee.data.lower()

    client.post("/auth/logout")
    sign_in(client, "other-manager@example.com")
    assert client.get("/team").status_code == 200
    assert client.post(
        f"/projects/{project_id}/sprints/new",
        data={
            "name": "Forbidden",
            "sprint_goal": "",
            "start_date": "2026-01-05",
            "end_date": "2026-01-10",
            "status": "planned",
        },
    ).status_code == 403


def test_phase3_migration_adds_columns_without_losing_existing_data(tmp_path):
    from sqlalchemy import inspect, text

    database_path = tmp_path / "existing-phase2.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username VARCHAR(64) UNIQUE NOT NULL,
            email VARCHAR(120) UNIQUE NOT NULL,
            password_hash VARCHAR(256) NOT NULL,
            role VARCHAR(32) NOT NULL DEFAULT 'team_member',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO users (username, email, password_hash)
        VALUES ('legacy', 'legacy@example.com', 'legacy-hash');
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            name VARCHAR(120) NOT NULL,
            description TEXT,
            start_date DATE,
            end_date DATE,
            status VARCHAR(32) NOT NULL DEFAULT 'planning',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO projects (name, status) VALUES ('Preserved', 'active');
        CREATE TABLE team_members (
            id INTEGER PRIMARY KEY,
            user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
            name VARCHAR(120) NOT NULL,
            skills TEXT NOT NULL DEFAULT '',
            available_hours FLOAT NOT NULL DEFAULT 0,
            daily_capacity FLOAT NOT NULL DEFAULT 8,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO team_members (name, skills) VALUES ('Legacy member', 'Python');
        """
    )
    connection.commit()
    connection.close()

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase3-test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        }
    )
    try:
        with app.app_context():
            assert Project.query.one().name == "Preserved"
            assert TeamMember.query.one().name == "Legacy member"
            assert User.query.one().email == "legacy@example.com"
            project_columns = {
                column["name"] for column in inspect(db.engine).get_columns("projects")
            }
            member_columns = {
                column["name"]
                for column in inspect(db.engine).get_columns("team_members")
            }
            assert "owner_id" in project_columns
            assert "email" in member_columns
            project_foreign_keys = inspect(db.engine).get_foreign_keys("projects")
            assert any(
                foreign_key["constrained_columns"] == ["owner_id"]
                and foreign_key["referred_table"] == "users"
                for foreign_key in project_foreign_keys
            )
            assert db.session.execute(
                text("PRAGMA foreign_key_check")
            ).all() == []
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_management_routes_require_authentication_and_restrict_team_members(app, client):
    protected_paths = (
        "/projects",
        "/sprints",
        "/team",
        "/tasks",
        "/projects/new",
        "/team/new",
        "/tasks/new",
    )
    for path in protected_paths:
        assert client.get(path).status_code == 302

    add_user(app, "developer", "team_member")
    sign_in(client, "developer@example.com")
    assert client.get("/projects").status_code == 200
    assert client.get("/sprints").status_code == 200
    assert client.get("/tasks").status_code == 200
    assert client.get("/team").status_code == 403
    assert client.get("/projects/new").status_code == 403
    assert client.get("/team/new").status_code == 403
    assert client.get("/tasks/new").status_code == 403
