import pytest

from app import create_app, db


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "test_sprintiq.db"
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
        }
    )

    yield app

    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def test_app_uses_configured_sqlite_database(app, tmp_path):
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
    assert (tmp_path / "test_sprintiq.db").exists()


def test_dashboard_renders_shared_layout(client):
    anonymous_response = client.get("/")
    assert anonymous_response.status_code == 302
    assert "/auth/login" in anonymous_response.location

    response = client.get("/auth/login")

    assert response.status_code == 200
    assert b"SprintIQ" in response.data
    assert b"Welcome back" in response.data


def test_health_endpoint_returns_status_json(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


@pytest.mark.parametrize(
    "asset_path",
    ["css/main.css", "js/main.js"],
)
def test_static_assets_are_served(client, asset_path):
    response = client.get(f"/static/{asset_path}")

    assert response.status_code == 200
    assert response.data


def test_unknown_route_returns_not_found(client):
    response = client.get("/not-a-phase1-route")

    assert response.status_code == 404