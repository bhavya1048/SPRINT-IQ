import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.models import Project, Sprint, Task, TaskAssignment, TeamMember, User


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'phase2.db'}",
        }
    )
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, username="sam", email="sam@example.com", password="secure-pass-123"):
    return client.post(
        "/auth/register",
        data={
            "username": username,
            "email": email,
            "password": password,
            "password2": password,
        },
        follow_redirects=True,
    )


def login(client, email="sam@example.com", password="secure-pass-123"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_registration_hashes_password_and_assigns_safe_default_role(client, app):
    response = register(client, email="SAM@example.com")

    assert response.status_code == 200
    assert b"Registration successful" in response.data
    with app.app_context():
        user = User.query.one()
        assert user.email == "sam@example.com"
        assert user.role == "team_member"
        assert user.password_hash != "secure-pass-123"
        assert user.check_password("secure-pass-123")


def test_duplicate_username_and_email_are_rejected(client):
    register(client)
    username_response = register(client, email="another@example.com")
    email_response = register(client, username="another")

    assert b"Please use a different username" in username_response.data
    assert b"Please use a different email address" in email_response.data


def test_invalid_email_and_mismatched_password_are_rejected(client):
    invalid_email = client.post(
        "/auth/register",
        data={"username": "sam", "email": "invalid", "password": "secure-pass-123", "password2": "secure-pass-123"},
    )
    mismatch = client.post(
        "/auth/register",
        data={"username": "sam", "email": "sam@example.com", "password": "secure-pass-123", "password2": "different-pass"},
    )

    assert b"valid email address" in invalid_email.data.lower()
    assert b"must be equal" in mismatch.data.lower()


def test_login_and_wrong_password(client):
    register(client)

    wrong = login(client, password="incorrect-password")
    assert b"Invalid email or password" in wrong.data

    correct = login(client)
    assert correct.status_code == 200
    assert b"sam" in correct.data
    assert client.get("/").status_code == 200


def test_logout_requires_post_and_clears_session(client):
    register(client)
    login(client)

    assert client.get("/auth/logout").status_code == 405
    response = client.post("/auth/logout", follow_redirects=True)

    assert b"You have been logged out" in response.data
    assert client.get("/").status_code == 302


def test_login_required_and_role_restriction(client, app):
    assert client.get("/").status_code == 302
    assert client.get("/auth/admin").status_code == 302
    register(client)
    login(client)
    assert client.get("/auth/admin").status_code == 403

    with app.app_context():
        user = User.query.one()
        user.role = "administrator"
        db.session.commit()
    assert client.get("/auth/admin").status_code == 200


def test_external_next_redirect_is_rejected(client):
    register(client)
    response = client.post(
        "/auth/login?next=https://example.com",
        data={"email": "sam@example.com", "password": "secure-pass-123"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_csrf_rejects_missing_token(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'csrf.db'}",
        }
    )
    try:
        response = app.test_client().post(
            "/auth/register",
            data={"username": "sam", "email": "sam@example.com", "password": "secure-pass-123", "password2": "secure-pass-123"},
        )
        assert response.status_code == 400
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()


def test_model_relationships_and_foreign_keys(app):
    with app.app_context():
        user = User(username="dev", email="dev@example.com", role="team_member")
        user.set_password("secure-pass-123")
        project = Project(name="Project")
        member = TeamMember(name="Developer", user=user, skills="Python", available_hours=20, daily_capacity=6)
        sprint = Sprint(project=project, name="Sprint 1", start_date=__import__("datetime").date(2026, 1, 1), end_date=__import__("datetime").date(2026, 1, 14))
        task = Task(sprint=sprint, title="Implement feature", estimated_hours=5)
        assignment = TaskAssignment(task=task, team_member=member, assigned_hours=5)
        db.session.add_all([user, project, member, sprint, task, assignment])
        db.session.commit()

        assert user.team_member.name == "Developer"
        assert project.sprints[0].tasks[0].assignments[0].team_member_id == member.id
        assert {"users", "projects", "team_members", "sprints", "tasks", "task_assignments"}.issubset(db.metadata.tables)

        with pytest.raises(IntegrityError):
            db.session.execute(
            text(
                    "INSERT INTO sprints "
                    "(project_id, name, start_date, end_date, status) "
                    "VALUES (99999, 'Invalid', '2026-01-01', '2026-01-07', 'planned')"
                )
            )
            db.session.commit()
        db.session.rollback()


def test_deleting_team_member_cascades_assignments(app):
    from datetime import date

    with app.app_context():
        project = Project(name="Project")
        sprint = Sprint(
            project=project,
            name="Sprint",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 14),
        )
        task = Task(sprint=sprint, title="Task")
        member = TeamMember(name="Developer")
        assignment = TaskAssignment(task=task, team_member=member, assigned_hours=2)
        db.session.add_all([project, member, sprint, task, assignment])
        db.session.commit()

        db.session.delete(member)
        db.session.commit()

        assert TaskAssignment.query.count() == 0


def test_legacy_users_table_is_upgraded_without_losing_rows(tmp_path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) UNIQUE NOT NULL, "
        "email VARCHAR(120) UNIQUE NOT NULL, password_hash VARCHAR(128) NOT NULL)"
    )
    connection.execute(
        "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
        ("legacy", "legacy@example.com", "existing-hash"),
    )
    connection.commit()
    connection.close()

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        }
    )
    try:
        with app.app_context():
            user = User.query.filter_by(username="legacy").one()
            assert user.email == "legacy@example.com"
            assert user.role == "team_member"
            assert user.created_at is not None
            created_at_column = next(
                column for column in db.inspect(db.engine).get_columns("users")
                if column["name"] == "created_at"
            )
            assert created_at_column["nullable"] is False
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()