import pytest
from fastapi.testclient import TestClient
from datetime import timedelta

# Import your unified web primitives directly from your main application script
from main import app, get_db, UserModel
from main import generate_access_token, pwd_context

# Standard mock session fixture for database sandboxing
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database_persistence import Base

# Setup an isolated in-memory SQLite database for secure testing
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(name="db_session")
def fixture_db_session():
    """Generates an isolated database session, building and teardown schemas per run."""
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)

@pytest.fixture(name="test_client")
def fixture_test_client(db_session):
    """Overloads production database dependency parameters injects test sandbox sessions."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    # Used as a context manager (not just `TestClient(app)`) so FastAPI's
    # lifespan actually runs -- main.py now compiles `agent_graph` inside its
    # lifespan handler (it needs to `async with AsyncSqliteSaver...` to open
    # the checkpoint connection, which can't happen at bare module-import
    # time). Without entering the context here, `agent_graph` stays None and
    # the takeover tests below would fail with an AttributeError instead of
    # actually exercising the security checks they're meant to test.
    with TestClient(app) as client:
        yield client
    # Clear overrides out cleanly post run tracking cycles
    app.dependency_overrides.clear()


def test_user_registration_enforces_cryptographic_hashing(test_client, db_session):
    """Verifies user registration stores hashed values, protecting raw plain-text passwords."""
    reg_payload = {
        "username": "supervisor_sarah",
        "email": "sarah@enterprise.com",
        "password": "SecurePassword2026!",
        "role": "admin"
    }

    response = test_client.post("/api/v1/auth/register", json=reg_payload)
    assert response.status_code == 201
    assert "account_id" in response.json()

    # Query the database directly to verify cryptographic isolation properties
    user_record = db_session.query(UserModel).filter(UserModel.username == "supervisor_sarah").first()
    assert user_record is not None
    assert user_record.hashed_password != "SecurePassword2026!"
    assert pwd_context.verify("SecurePassword2026!", user_record.hashed_password) is True


def test_takeover_route_strictly_blocks_unauthenticated_requests(test_client):
    """Verifies that requests omitting bearer tokens are blocked instantly at gateway borders."""
    takeover_payload = {
        "thread_id": "customer_ticket_999",
        "override_message": "Unauthorized administrative hijack text."
    }
    response = test_client.post("/api/v1/support/takeover", json=takeover_payload)

    assert response.status_code == 401
    assert "Not authenticated" in response.text


def test_takeover_route_denies_access_to_low_privilege_roles(test_client):
    """Verifies that low privilege tokens (role='agent') are caught and rejected by role filters."""
    # Generate a signed token lacking administrative permissions
    limited_token = generate_access_token(
        data={"sub": "agent_bob", "role": "agent"},
        expires_delta=timedelta(minutes=15)
    )
    headers = {"Authorization": f"Bearer {limited_token}"}
    takeover_payload = {
        "thread_id": "customer_ticket_999",
        "override_message": "Attempted takeover from restricted role account."
    }

    response = test_client.post("/api/v1/support/takeover", json=takeover_payload, headers=headers)

    assert response.status_code == 403
    assert "Administrative privileges required" in response.json()["detail"]


def test_takeover_route_authorizes_valid_admin_tokens(test_client):
    """Verifies that a verified administrative user passes security checkpoints cleanly."""
    valid_admin_token = generate_access_token(
        data={"sub": "supervisor_clara", "role": "admin"},
        expires_delta=timedelta(minutes=15)
    )
    headers = {"Authorization": f"Bearer {valid_admin_token}"}
    takeover_payload = {
        "thread_id": "customer_ticket_999",
        "override_message": "Authorized administrative intercept text."
    }

    response = test_client.post("/api/v1/support/takeover", json=takeover_payload, headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert response.json()["operator"] == "supervisor_clara"
