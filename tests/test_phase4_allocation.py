import sqlite3
from datetime import date

import pytest

from app import create_app, db
from app.management.allocation import (
    candidate_score,
    count_working_days,
    member_workload,
    parse_skills,
    ranked_recommendations,
    skill_match_score,
    sprint_capacity,
)
from app.models import (
    AllocationRejection,
    Project,
    Sprint,
    Task,
    TaskAssignment,
    TeamMember,
    User,
)


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase4-test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'phase4.db'}",
        }
    )
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def add_user(app, username, role):
    with app.app_context():
        user = User(
            username=username,
            email=f"{username}@example.com",
            role=role,
        )
        user.set_password("phase4-password")
        db.session.add(user)
        db.session.commit()
        return user.id


def sign_in(client, username):
    return client.post(
        "/auth/login",
        data={
            "email": f"{username}@example.com",
            "password": "phase4-password",
        },
        follow_redirects=True,
    )


def create_sprint_data(app, manager_id, members, task_data):
    with app.app_context():
        manager = db.session.get(User, manager_id)
        project = Project(
            owner=manager,
            name="Allocation project",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            status="active",
        )
        sprint = Sprint(
            project=project,
            name="Allocation sprint",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 16),
            status="active",
        )
        db.session.add_all([project, sprint, *members])
        db.session.flush()
        task = Task(
            sprint=sprint,
            title=task_data.get("title", "Implement feature"),
            description="Allocation test task",
            required_skills=task_data.get("required_skills", "Python"),
            priority=task_data.get("priority", "high"),
            estimated_hours=task_data.get("estimated_hours", 8),
            status="todo",
        )
        db.session.add(task)
        db.session.commit()
        return sprint.id, task.id, [member.id for member in members]


def test_skill_matching_is_normalized_and_handles_missing_skills():
    assert parse_skills(" Python, sql;\nFlask ") == {"python", "sql", "flask"}
    assert skill_match_score("Python, SQL", "python;JavaScript") == 50
    assert skill_match_score("Python", "") == 0
    assert skill_match_score("", "") == 100


def test_capacity_and_availability_use_stored_hours_and_sprint_weekdays(app):
    manager_id = add_user(app, "capacity-manager", "project_manager")
    member = TeamMember(
        name="Developer",
        skills="Python",
        available_hours=45,
        daily_capacity=6,
    )
    sprint_id, _task_id, _member_ids = create_sprint_data(
        app, manager_id, [member], {"estimated_hours": 5}
    )
    with app.app_context():
        sprint = db.session.get(Sprint, sprint_id)
        saved_member = TeamMember.query.one()
        result = sprint_capacity(saved_member, sprint)
        workload = member_workload(saved_member, sprint)

    assert count_working_days(sprint) == 10
    assert result == {
        "working_days": 10,
        "theoretical_capacity": 60,
        "capacity": 45,
        "availability_score": 75,
    }
    assert workload["remaining"] == 45
    assert workload["utilization"] == 0
    assert workload["classification"] == "underutilized"


def test_workload_counts_existing_allocations_and_detects_overload(app):
    manager_id = add_user(app, "workload-manager", "project_manager")
    member = TeamMember(
        name="Developer",
        skills="Python",
        available_hours=60,
        daily_capacity=6,
    )
    sprint_id, task_id, _member_ids = create_sprint_data(
        app, manager_id, [member], {"estimated_hours": 8}
    )
    with app.app_context():
        task = db.session.get(Task, task_id)
        saved_member = TeamMember.query.one()
        db.session.add(
            TaskAssignment(task=task, team_member=saved_member, assigned_hours=64)
        )
        db.session.commit()
        result = member_workload(saved_member, task.sprint)

    assert result["capacity"] == 60
    assert result["allocated"] == 64
    assert result["remaining"] == -4
    assert result["classification"] == "overloaded"
    assert result["utilization"] > 100


def test_workload_thresholds_are_configurable(app):
    manager_id = add_user(app, "threshold-manager", "project_manager")
    member = TeamMember(
        name="Developer",
        skills="Python",
        available_hours=60,
        daily_capacity=6,
    )
    sprint_id, task_id, _member_ids = create_sprint_data(
        app, manager_id, [member], {"estimated_hours": 8}
    )
    with app.app_context():
        task = db.session.get(Task, task_id)
        saved_member = TeamMember.query.one()
        db.session.add(
            TaskAssignment(task=task, team_member=saved_member, assigned_hours=64)
        )
        db.session.commit()
        sprint = db.session.get(Sprint, sprint_id)
        workload = member_workload(
            saved_member, sprint, underutilized_threshold=20, overload_threshold=110
        )

    assert workload["classification"] == "balanced"


def test_weighted_score_matches_formula_and_candidates_are_ranked(app):
    manager_id = add_user(app, "score-manager", "project_manager")
    lower_availability = TeamMember(
        name="A Developer",
        skills="Python, SQL",
        available_hours=30,
        daily_capacity=6,
    )
    higher_availability = TeamMember(
        name="B Developer",
        skills="Python, SQL",
        available_hours=60,
        daily_capacity=6,
    )
    sprint_id, task_id, _member_ids = create_sprint_data(
        app,
        manager_id,
        [lower_availability, higher_availability],
        {"estimated_hours": 8, "required_skills": "Python, SQL", "priority": "high"},
    )
    with app.app_context():
        sprint = db.session.get(Sprint, sprint_id)
        task = db.session.get(Task, task_id)
        workloads = [
            member_workload(member, sprint)
            for member in TeamMember.query.order_by(TeamMember.name).all()
        ]
        candidate = candidate_score(task, workloads[0])
        ranked = ranked_recommendations(task, workloads)

    assert candidate["skill_match"] == 100
    assert candidate["capacity_score"] == 100
    assert candidate["availability_score"] == 50
    assert candidate["priority_suitability"] == 90
    assert candidate["score"] == pytest.approx(
        0.4 * 100 + 0.3 * 100 + 0.2 * 50 + 0.1 * 90
    )
    assert [item["member"].name for item in ranked] == [
        "B Developer",
        "A Developer",
    ]
    assert all(0 <= item["score"] <= 100 for item in ranked)
    assert all(
        {"skills", "capacity", "availability", "workload"}
        == set(item["explanations"])
        for item in ranked
    )


def test_zero_skill_match_and_insufficient_capacity_are_not_recommended(app):
    manager_id = add_user(app, "eligibility-manager", "project_manager")
    no_skills = TeamMember(
        name="No Match",
        skills="Design",
        available_hours=60,
        daily_capacity=6,
    )
    insufficient_capacity = TeamMember(
        name="Overloaded",
        skills="Python",
        available_hours=4,
        daily_capacity=6,
    )
    eligible = TeamMember(
        name="Eligible",
        skills="Python",
        available_hours=60,
        daily_capacity=6,
    )
    sprint_id, task_id, _member_ids = create_sprint_data(
        app,
        manager_id,
        [no_skills, insufficient_capacity, eligible],
        {"estimated_hours": 8},
    )
    with app.app_context():
        sprint = db.session.get(Sprint, sprint_id)
        task = db.session.get(Task, task_id)
        workloads = [
            member_workload(member, sprint)
            for member in TeamMember.query.order_by(TeamMember.name).all()
        ]
        ranked = ranked_recommendations(task, workloads)
        scored = {item["member"].name: item for item in (candidate_score(task, w) for w in workloads)}

    assert [item["member"].name for item in ranked] == ["Eligible"]
    assert not scored["No Match"]["eligible"]
    assert not scored["Overloaded"]["eligible"]


def test_manager_can_view_and_accept_recommendation_persistently(app, client):
    manager_id = add_user(app, "approval-manager", "project_manager")
    member = TeamMember(
        name="Developer",
        skills="Python",
        available_hours=40,
        daily_capacity=8,
    )
    sprint_id, task_id, member_ids = create_sprint_data(app, manager_id, [member], {})
    sign_in(client, "approval-manager")

    page = client.get(f"/allocations?sprint_id={sprint_id}")
    assert page.status_code == 200
    assert b"Developer" in page.data
    assert b"Approve assignment" in page.data
    with app.app_context():
        assert TaskAssignment.query.count() == 0

    response = client.post(
        f"/allocations/{task_id}/accept/{member_ids[0]}",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Recommended assignment approved" in response.data
    with app.app_context():
        db.session.remove()
        assignment = TaskAssignment.query.one()
        assert assignment.task_id == task_id
        assert assignment.team_member_id == member_ids[0]
        assert assignment.assigned_hours == 8


def test_accept_revalidates_capacity_before_persisting(app, client):
    manager_id = add_user(app, "stale-manager", "project_manager")
    member = TeamMember(
        name="Developer",
        skills="Python",
        available_hours=10,
        daily_capacity=2,
    )
    sprint_id, task_id, member_ids = create_sprint_data(
        app, manager_id, [member], {"estimated_hours": 8}
    )
    with app.app_context():
        sprint = db.session.get(Sprint, sprint_id)
        second_task = Task(
            sprint=sprint,
            title="Another task",
            required_skills="Python",
            estimated_hours=8,
            status="todo",
        )
        db.session.add(second_task)
        db.session.commit()
        second_task_id = second_task.id

    sign_in(client, "stale-manager")
    with app.app_context():
        second_task = db.session.get(Task, second_task_id)
        db.session.add(
            TaskAssignment(
                task=second_task,
                team_member_id=member_ids[0],
                assigned_hours=8,
            )
        )
        db.session.commit()

    response = client.post(
        f"/allocations/{task_id}/accept/{member_ids[0]}",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"recommendation is no longer eligible" in response.data
    with app.app_context():
        assignments = TaskAssignment.query.all()
        assert len(assignments) == 1
        assert assignments[0].task_id == second_task_id


def test_task_form_saves_required_skills(app, client):
    manager_id = add_user(app, "skills-form-manager", "project_manager")
    sprint_id, _task_id, _member_ids = create_sprint_data(app, manager_id, [], {})
    sign_in(client, "skills-form-manager")

    response = client.post(
        "/tasks/new",
        data={
            "sprint_id": str(sprint_id),
            "title": "Build API",
            "description": "Create a service endpoint",
            "required_skills": "Python, Flask",
            "priority": "high",
            "estimated_hours": "4",
            "status": "todo",
            "due_date": "2026-01-15",
            "team_member_ids": [],
            "assigned_hours": "0",
        },
    )

    assert response.status_code == 302
    with app.app_context():
        task = Task.query.filter_by(title="Build API").one()
        assert task.required_skills == "Python, Flask"


def test_task_form_blocks_capacity_overrun_without_manager_override(app, client):
    manager_id = add_user(app, "task-capacity-manager", "project_manager")
    member = TeamMember(
        name="Developer",
        skills="Python",
        available_hours=4,
        daily_capacity=2,
    )
    sprint_id, _task_id, member_ids = create_sprint_data(
        app, manager_id, [member], {"estimated_hours": 1}
    )
    sign_in(client, "task-capacity-manager")
    task_data = {
        "sprint_id": str(sprint_id),
        "title": "Capacity-limited task",
        "description": "",
        "required_skills": "Python",
        "priority": "high",
        "estimated_hours": "8",
        "status": "todo",
        "due_date": "2026-01-15",
        "team_member_ids": [str(member_ids[0])],
        "assigned_hours": "5",
    }

    rejected = client.post("/tasks/new", data=task_data)
    assert rejected.status_code == 200
    assert b"insufficient remaining sprint capacity" in rejected.data
    with app.app_context():
        assert Task.query.filter_by(title="Capacity-limited task").count() == 0
        assert TaskAssignment.query.count() == 0

    overridden = client.post(
        "/tasks/new",
        data={**task_data, "confirm_allocation_override": "y"},
    )
    assert overridden.status_code == 302
    with app.app_context():
        task = Task.query.filter_by(title="Capacity-limited task").one()
        assignment = TaskAssignment.query.one()
        assert assignment.task_id == task.id
        assert assignment.assigned_hours == 5


def test_rejection_persists_without_assigning_task(app, client):
    manager_id = add_user(app, "rejection-manager", "project_manager")
    member = TeamMember(
        name="Developer",
        skills="Python",
        available_hours=40,
        daily_capacity=8,
    )
    sprint_id, task_id, member_ids = create_sprint_data(app, manager_id, [member], {})
    sign_in(client, "rejection-manager")

    response = client.post(
        f"/allocations/{task_id}/reject/{member_ids[0]}",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Recommendation rejected" in response.data
    assert b"No eligible recommendations" in response.data
    with app.app_context():
        assert TaskAssignment.query.count() == 0
        assert AllocationRejection.query.filter_by(
            task_id=task_id, team_member_id=member_ids[0]
        ).count() == 1


def test_manual_override_requires_confirmation_for_ineligible_member(app, client):
    manager_id = add_user(app, "override-manager", "project_manager")
    member = TeamMember(
        name="Unavailable Specialist",
        skills="Design",
        available_hours=0,
        daily_capacity=0,
    )
    sprint_id, task_id, member_ids = create_sprint_data(app, manager_id, [member], {})
    sign_in(client, "override-manager")
    override_url = f"/allocations/{task_id}/override"

    refused = client.post(
        override_url,
        data={"team_member_id": str(member_ids[0])},
        follow_redirects=True,
    )
    assert refused.status_code == 200
    assert b"Confirm the skill/capacity override" in refused.data
    with app.app_context():
        assert TaskAssignment.query.count() == 0

    accepted = client.post(
        override_url,
        data={
            "team_member_id": str(member_ids[0]),
            "confirm_override": "y",
        },
        follow_redirects=True,
    )
    assert accepted.status_code == 200
    assert b"Manual assignment saved" in accepted.data
    with app.app_context():
        db.session.remove()
        assignment = TaskAssignment.query.one()
        assert assignment.task_id == task_id
        assert assignment.team_member_id == member_ids[0]
        assert assignment.assigned_hours == 8


def test_team_members_cannot_access_manager_allocation_controls(app, client):
    manager_id = add_user(app, "owner-manager", "project_manager")
    member_user_id = add_user(app, "team-user", "team_member")
    member = TeamMember(
        user_id=member_user_id,
        name="Team User",
        skills="Python",
        available_hours=40,
        daily_capacity=8,
    )
    sprint_id, task_id, member_ids = create_sprint_data(app, manager_id, [member], {})

    sign_in(client, "team-user")
    assert client.get("/allocations").status_code == 403
    assert client.post(
        f"/allocations/{task_id}/accept/{member_ids[0]}"
    ).status_code == 403
    assert client.post(
        f"/allocations/{task_id}/reject/{member_ids[0]}"
    ).status_code == 403
    assert client.post(
        f"/allocations/{task_id}/override",
        data={"team_member_id": str(member_ids[0]), "confirm_override": "y"},
    ).status_code == 403
    with app.app_context():
        assert TaskAssignment.query.count() == 0


def test_phase4_schema_migration_preserves_existing_tasks(tmp_path):
    database_path = tmp_path / "phase3-existing.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            sprint_id INTEGER NOT NULL,
            title VARCHAR(200) NOT NULL,
            description TEXT,
            priority VARCHAR(32) NOT NULL DEFAULT 'medium',
            estimated_hours FLOAT NOT NULL DEFAULT 0,
            status VARCHAR(32) NOT NULL DEFAULT 'todo',
            due_date DATE
        );
        INSERT INTO tasks
            (id, sprint_id, title, description, priority, estimated_hours, status)
        VALUES
            (12, 4, 'Existing task', 'Keep this row', 'high', 5, 'todo');
        """
    )
    connection.commit()
    connection.close()

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase4-migration-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        }
    )
    try:
        with app.app_context():
            task = db.session.get(Task, 12)
            assert task.title == "Existing task"
            assert task.description == "Keep this row"
            assert task.required_skills == ""
            assert db.inspect(db.engine).has_table("allocation_rejections")
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
