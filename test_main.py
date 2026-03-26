import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, get_db
from main import app

# ----------------------------
# TEST DATABASE SETUP
# Use a separate SQLite DB for tests
# so we don't mess up real data
# ----------------------------

TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def override_get_db():
    """Use test database instead of real one"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override the database dependency
app.dependency_overrides[get_db] = override_get_db

# Create test client
client = TestClient(app)


# ----------------------------
# SETUP & TEARDOWN
# ----------------------------

@pytest.fixture(autouse=True)
def setup_database():
    """Create tables before each test, drop after"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


# ----------------------------
# HELPER FUNCTIONS
# ----------------------------

def register_user(username="testuser", password="testpass123"):
    """Helper to register a user"""
    return client.post("/auth/register", json={
        "username":  username,
        "password":  password,
        "full_name": "Test User",
        "email":     f"{username}@test.com"
    })


def login_user(username="testuser", password="testpass123"):
    """Helper to login and get token"""
    res = client.post("/auth/login", data={
        "username": username,
        "password": password
    })
    return res.json()["access_token"]


def auth_headers(token):
    """Helper to build auth headers"""
    return {"Authorization": f"Bearer {token}"}


# ----------------------------
# HEALTH CHECK TESTS
# ----------------------------

def test_health_check():
    """API should return ok status"""
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# ----------------------------
# AUTH TESTS
# ----------------------------

def test_register_success():
    """User should register successfully"""
    res = register_user()
    assert res.status_code == 201
    assert "registered successfully" in res.json()["message"]


def test_register_duplicate_username():
    """Duplicate username should fail"""
    register_user()
    res = register_user()  # register same user again
    assert res.status_code == 400
    assert "already exists" in res.json()["detail"]


def test_login_success():
    """User should login and get a token"""
    register_user()
    res = client.post("/auth/login", data={
        "username": "testuser",
        "password": "testpass123"
    })
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_login_wrong_password():
    """Wrong password should fail"""
    register_user()
    res = client.post("/auth/login", data={
        "username": "testuser",
        "password": "wrongpassword"
    })
    assert res.status_code == 401


def test_get_me():
    """Should return current user info"""
    register_user()
    token = login_user()
    res = client.get("/auth/me", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json()["username"] == "testuser"


# ----------------------------
# TASK TESTS
# ----------------------------

def test_get_tasks_unauthenticated():
    """Should block unauthenticated requests"""
    res = client.get("/tasks")
    assert res.status_code == 401


def test_create_task():
    """Should create a task successfully"""
    register_user()
    token = login_user()
    res = client.post("/tasks",
        json={"title": "Test task", "priority": "high"},
        headers=auth_headers(token)
    )
    assert res.status_code == 201
    assert res.json()["title"] == "Test task"
    assert res.json()["priority"] == "high"
    assert res.json()["done"] == False


def test_create_task_short_title():
    """Title too short should fail"""
    register_user()
    token = login_user()
    res = client.post("/tasks",
        json={"title": "Hi"},
        headers=auth_headers(token)
    )
    assert res.status_code == 422


def test_create_task_invalid_priority():
    """Invalid priority should fail"""
    register_user()
    token = login_user()
    res = client.post("/tasks",
        json={"title": "Test task", "priority": "urgent"},
        headers=auth_headers(token)
    )
    assert res.status_code == 422


def test_get_all_tasks():
    """Should return all tasks for current user"""
    register_user()
    token = login_user()
    headers = auth_headers(token)

    # Create 2 tasks
    client.post("/tasks", json={"title": "Task one"}, headers=headers)
    client.post("/tasks", json={"title": "Task two"}, headers=headers)

    res = client.get("/tasks", headers=headers)
    assert res.status_code == 200
    assert res.json()["count"] == 2


def test_get_single_task():
    """Should return a single task by ID"""
    register_user()
    token = login_user()
    headers = auth_headers(token)

    # Create task
    created = client.post("/tasks",
        json={"title": "Single task"},
        headers=headers
    ).json()

    res = client.get(f"/tasks/{created['id']}", headers=headers)
    assert res.status_code == 200
    assert res.json()["title"] == "Single task"


def test_update_task():
    """Should update a task successfully"""
    register_user()
    token = login_user()
    headers = auth_headers(token)

    created = client.post("/tasks",
        json={"title": "Old title", "priority": "low"},
        headers=headers
    ).json()

    res = client.put(f"/tasks/{created['id']}",
        json={"title": "New title", "priority": "high", "done": False},
        headers=headers
    )
    assert res.status_code == 200
    assert res.json()["title"] == "New title"
    assert res.json()["priority"] == "high"


def test_mark_task_done():
    """Should mark a task as done"""
    register_user()
    token = login_user()
    headers = auth_headers(token)

    created = client.post("/tasks",
        json={"title": "Finish this"},
        headers=headers
    ).json()

    res = client.patch(f"/tasks/{created['id']}/done", headers=headers)
    assert res.status_code == 200
    assert res.json()["task"]["done"] == True


def test_delete_task():
    """Should delete a task"""
    register_user()
    token = login_user()
    headers = auth_headers(token)

    created = client.post("/tasks",
        json={"title": "Delete me"},
        headers=headers
    ).json()

    res = client.delete(f"/tasks/{created['id']}", headers=headers)
    assert res.status_code == 200

    # Verify it's gone
    res = client.get(f"/tasks/{created['id']}", headers=headers)
    assert res.status_code == 404


def test_task_isolation():
    """Users should not see each other's tasks"""
    # Register two users
    register_user("user1", "pass123456")
    register_user("user2", "pass123456")

    token1 = login_user("user1", "pass123456")
    token2 = login_user("user2", "pass123456")

    # User1 creates a task
    created = client.post("/tasks",
        json={"title": "User1 task"},
        headers=auth_headers(token1)
    ).json()

    # User2 tries to access it
    res = client.get(f"/tasks/{created['id']}",
        headers=auth_headers(token2)
    )
    assert res.status_code == 403