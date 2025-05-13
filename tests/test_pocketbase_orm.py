import os
from datetime import datetime, timezone
from enum import Enum
from typing import Union
import uuid
import subprocess
import time
import httpx
import signal

import pytest
from pocketbase.client import FileUpload
from pydantic import AnyUrl, EmailStr, Field

from pocketbase_orm import PBModel, User, PBReference


class RelatedModel(PBModel, collection="related_models"):
    name: str


class Example(PBModel):
    text_field: str
    number_field: int
    is_active: bool
    url_field: AnyUrl
    created_at: datetime
    options: list[str]
    email_field: EmailStr | None = None
    related_model: PBReference[RelatedModel]
    image: Union[FileUpload, str] | None = Field(
        default=None, description="Image file upload"
    )


class UserType(str, Enum):
    ADMIN = "admin"
    REGULAR = "regular"
    GUEST = "guest"


class ModelWithEnum(PBModel, collection="enum_models"):
    name: str
    user_type: UserType  # Using the actual enum type


@pytest.fixture(scope="session")
def pb_client():
    """Fixture to provide an authenticated PocketBase client."""
    username = os.getenv("POCKETBASE_USERNAME", "admin@pb.com")
    password = os.getenv("POCKETBASE_PASSWORD", "mamaistdiebeste")
    url = os.getenv("POCKETBASE_URL", "http://127.0.0.1:4419")

    if not all([username, password, url]):
        raise ValueError("PocketBase credentials not set in environment")

    process = None
    # PocketBase standard health endpoint
    health_endpoint = "/api/health"
    base_url_for_health_check = url.rstrip("/")
    health_check_full_url = f"{base_url_for_health_check}{health_endpoint}"

    try:
        popen_kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen(["just", "reset-pocketbase"], **popen_kwargs)

        time.sleep(1.0)
        if process.poll() is not None:
            stdout_output, stderr_output = process.communicate()
            pytest.fail(f"STDOUT:\n{stdout_output}\nSTDERR:\n{stderr_output}")
        print(f"PocketBase process started (PID: {process.pid}).")

        # --- Health Check using httpx ---
        print(
            f"Performing health check for PocketBase at {health_check_full_url} using httpx..."
        )
        max_retries = 20
        retry_delay_seconds = 1.5
        healthy = False

        health_check_timeout = httpx.Timeout(5)

        with httpx.Client(timeout=health_check_timeout) as http_client:
            for attempt in range(max_retries):
                print(
                    f"Health check attempt {attempt + 1}/{max_retries} to {health_check_full_url}..."
                )
                try:
                    response = http_client.get(health_check_full_url)
                    response.raise_for_status()

                    if response.status_code == 200:
                        print(
                            f"PocketBase reported healthy (HTTP {response.status_code}) on attempt {attempt + 1}."
                        )
                        healthy = True
                        break
                    else:
                        print(
                            f"Health check attempt {attempt + 1}: Received unexpected status {response.status_code}. Expecting 200. Body: {response.text[:200]}"
                        )

                except Exception as e:  # Catch any other unexpected errors
                    print(
                        f"Health check attempt {attempt + 1}: Unexpected error - {type(e).__name__}: {e}"
                    )

                if attempt < max_retries - 1:
                    time.sleep(retry_delay_seconds)
                else:
                    pytest.fail(
                        f"PocketBase did not become healthy at {health_check_full_url} "
                        f"after {max_retries} attempts ({int(max_retries * retry_delay_seconds)} seconds).\n"
                    )

        if not healthy:
            pytest.fail("PocketBase health check definitively failed.")

        print("PocketBase is healthy. Initializing client...")
        client = PBModel.init_client(url, username, password)
        yield client

    finally:
        if process:
            if (
                os.name == "posix"
                and "start_new_session" in popen_kwargs
                and popen_kwargs["start_new_session"]
            ):
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    print("Sent SIGTERM to process group.")
                except ProcessLookupError:
                    print("Process group already terminated.")
                except Exception as e:
                    print(
                        f"Error sending SIGTERM to process group: {e}. Trying process.terminate()."
                    )
                    process.terminate()
            else:
                process.terminate()
                print("Sent terminate signal to process.")

            try:
                process.wait(timeout=10)
                print("PocketBase process terminated gracefully.")
            except subprocess.TimeoutExpired:
                print(
                    "PocketBase process did not terminate gracefully after 10s. Sending kill signal..."
                )
                if (
                    os.name == "posix"
                    and "start_new_session" in popen_kwargs
                    and popen_kwargs["start_new_session"]
                ):
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except Exception as e:
                        print(
                            f"Error sending SIGKILL to process group: {e}. Trying process.kill()."
                        )
                        process.kill()
                else:
                    process.kill()
                try:
                    process.wait(timeout=5)
                except Exception as e:
                    print(f"Error waiting for process after kill: {e}")
            except Exception as e:
                print(f"Error during process wait: {e}")

            try:
                # Best effort to get any final output
                stdout_output, stderr_output = process.communicate(timeout=1)
                if stdout_output:
                    print(f"Final PocketBase STDOUT:\n{stdout_output.strip()}")
                if stderr_output:
                    print(f"Final PocketBase STDERR:\n{stderr_output.strip()}")
            except Exception as e:
                print(f"Error reading stdout/stderr from process: {e}")


@pytest.fixture(scope="session")
def setup_models(pb_client):
    """Fixture to bind the client and sync collections."""
    PBModel.bind_client(pb_client)
    RelatedModel.sync_collection()
    Example.sync_collection()
    ModelWithEnum.sync_collection()
    yield
    ModelWithEnum.delete_collection()
    Example.delete_collection()
    RelatedModel.delete_collection()


@pytest.fixture(scope="session")
def related_model(setup_models):
    """Fixture to create and return a test RelatedModel instance."""
    model = RelatedModel(name="Test Related Model")
    model.save()
    yield model


def test_create_example_with_file(setup_models, related_model):
    """Test creating an Example record with a file upload."""
    with open("static/image.png", "rb") as f:
        example = Example(
            text_field="Test with image",
            number_field=123,
            is_active=True,
            email_field="test@example.com",
            url_field="http://example.com",
            created_at=datetime.now(timezone.utc),
            options=["option1", "option2"],
            related_model=related_model.id,
            image=FileUpload(("image.png", f)),
        )
        example.save()

        # Verify the record was created
        assert example.id != ""

        # Test retrieval methods
        retrieved = Example.get_one(example.id)
        assert retrieved.text_field == "Test with image"
        assert retrieved.number_field == 123
        assert retrieved.is_active is True

        # Test list retrieval
        examples = Example.get_full_list()
        assert len(examples) > 0
        assert any(e.id == example.id for e in examples)

        # Test filtering
        filtered = Example.get_first_list_item(f"email_field = '{example.email_field}'")
        assert filtered.id

        # Test file contents
        image_bytes = example.get_file_contents("image")
        assert len(image_bytes) > 0


def test_related_model_crud(setup_models):
    """Test CRUD operations for RelatedModel."""
    # Create
    model = RelatedModel(name="CRUD Test Model")
    model.save()
    assert model.id != ""

    # Read
    retrieved = RelatedModel.get_one(model.id)
    assert retrieved.name == "CRUD Test Model"

    # Update
    model.name = "Updated Name"
    model.save()
    updated = RelatedModel.get_one(model.id)
    assert updated.name == "Updated Name"

    # Delete
    RelatedModel.delete_by_id(model.id)
    with pytest.raises(Exception):
        RelatedModel.get_one(model.id)


def test_example_validation(setup_models, related_model):
    """Test validation rules for Example model."""
    # Test invalid email
    with pytest.raises(ValueError):
        Example(
            text_field="Test",
            number_field=123,
            is_active=True,
            email_field="invalid-email",  # Invalid email format
            url_field="http://example.com",
            created_at=datetime.now(timezone.utc),
            options=["option1"],
            related_model=related_model.id,
        )

    # Test invalid URL
    with pytest.raises(ValueError):
        Example(
            text_field="Test",
            number_field=123,
            is_active=True,
            email_field="test@example.com",
            url_field="invalid-url",  # Invalid URL format
            created_at=datetime.now(timezone.utc),
            options=["option1"],
            related_model=related_model.id,
        )


def test_get_list_pagination(setup_models, related_model):
    """Test pagination functionality of get_list method."""
    # Create multiple example records
    examples = []
    for i in range(1, 15):  # Create 15 records to test pagination
        example = Example(
            text_field=f"Test {i}",
            number_field=i,
            is_active=True,
            email_field=f"test{i}@example.com",
            url_field="http://example.com",
            created_at=datetime.now(timezone.utc),
            options=["option1"],
            related_model=related_model.id,
        )
        example.save()
        examples.append(example)

    # Test first page (5 items)
    page1 = Example.get_list(page=1, per_page=5)
    assert len(page1) == 5

    # Test second page (5 items)
    page2 = Example.get_list(page=2, per_page=5)
    assert len(page2) == 5

    # Verify different records on different pages
    page1_ids = {item.id for item in page1}
    page2_ids = {item.id for item in page2}
    assert not page1_ids.intersection(page2_ids)  # No overlap between pages

    # Test with filter
    filtered = Example.get_list(page=1, per_page=3, filter="number_field >= 10")
    assert len(filtered) == 3
    assert all(item.number_field >= 10 for item in filtered)


def test_user_collection_operations(setup_models):
    """Test that User model prevents collection creation/modification."""

    # Test that attempting to create users collection raises error
    with pytest.raises(RuntimeError) as exc_info:
        User._create_collection()
    assert "system collection" in str(exc_info.value)

    # Test that attempting to update users collection raises error
    with pytest.raises(RuntimeError) as exc_info:
        # Create mock collection object with minimal required attributes
        mock_collection = type(
            "MockCollection", (), {"id": "mock_id", "name": "users", "fields": []}
        )
        User._update_collection(mock_collection)
    assert "system collection" in str(exc_info.value)

    # Test that we can still create and work with User instances
    user = User(
        email="test@example.com", password="securepassword123", name="Test User"
    )
    assert user.email == "test@example.com"
    assert user.name == "Test User"


def test_user_crud_operations(setup_models):
    """Test CRUD operations for User model."""

    test_users = []

    email = f"test.user{uuid.uuid4()}@example.com"

    # Test creating a user
    user = User(
        email=email,
        password="securepassword123",
        passwordConfirm="securepassword123",
        name="Test User",
        emailVisibility=True,
    )
    user.save()
    assert user.id, "User should have an ID after saving"
    test_users.append(user)

    # Test get_one
    retrieved = User.get_one(user.id)
    assert retrieved.email == email
    assert retrieved.name == "Test User"
    assert retrieved.password is None  # Password should not be returned

    # Create more test users for list operations
    for i in range(1, 4):
        email = f"test.user{i}{uuid.uuid4()}@example.com"
        user = User(
            email=email,
            password="securepassword123",
            passwordConfirm="securepassword123",
            name=f"Test User {i}",
        ).save()
        test_users.append(user)

    # Test get_list with pagination
    users_page = User.get_list(page=1, per_page=2)
    assert len(users_page) == 2, "Should return 2 users per page"

    # Test get_full_list
    all_users = User.get_full_list()
    assert len(all_users) >= len(test_users), "Should return all test users"

    # Test get_first_list_item with filter
    first_user = User.get_first_list_item(f'email = "{email}"')
    assert first_user.email == email

    # Test updating a user
    user = test_users[0]
    user.name = "Updated Name"
    user.save()

    updated = User.get_one(user.id)
    assert updated.name == "Updated Name"

    for user in test_users:
        user.delete()


def test_sync_collection_add_fields(pb_client):
    """Test that sync_collection can add new fields to an existing collection."""

    collection_name = "test_sync_model"

    # Define initial model with basic fields
    class InitialModel(PBModel, collection=collection_name):
        name: str
        count: int

    # Bind client to the model
    InitialModel.bind_client(pb_client)

    try:
        # Clean up any existing collection from previous test runs
        try:
            InitialModel.delete_collection()
        except Exception as _:
            pass

        # 1. Create the collection with initial fields
        InitialModel.sync_collection()

        # Verify the collection exists with expected fields
        collection = pb_client.collections.get_one(collection_name)
        field_names = [field.name for field in collection.fields]

        # Should have name, count, created, and updated fields
        assert "name" in field_names
        assert "count" in field_names
        assert "created" in field_names
        assert "updated" in field_names
        assert "description" not in field_names  # Shouldn't have new fields yet
        assert "active" not in field_names

        # 2. Now define an extended model with additional fields
        class ExtendedModel(PBModel, collection=collection_name):
            name: str
            count: int
            description: str
            active: bool

        # Bind client and sync extended model to update the collection
        ExtendedModel.bind_client(pb_client)
        ExtendedModel.sync_collection()

        # Verify the collection now has the new fields
        updated_collection = pb_client.collections.get_one(collection_name)
        updated_field_names = [field.name for field in updated_collection.fields]

        # Should now have all fields including the new ones
        assert "name" in updated_field_names
        assert "count" in updated_field_names
        assert "created" in updated_field_names
        assert "updated" in updated_field_names
        assert "description" in updated_field_names  # New field should exist
        assert "active" in updated_field_names  # New field should exist

    finally:
        # Clean up
        try:
            InitialModel.delete_collection()
        except Exception as _:
            pass


def test_enum_field_handling(setup_models):
    """Test handling of enum fields in the model."""
    # Create an instance with an enum value
    instance = ModelWithEnum(name="Enum Test", user_type=UserType.ADMIN)
    instance.save()

    # Retrieve the instance and check that it's converted to the proper enum type
    retrieved = ModelWithEnum.get_one(instance.id)
    assert retrieved.user_type == UserType.ADMIN
    assert isinstance(retrieved.user_type, UserType)  # Verify it's the actual enum type

    # Test with another enum value
    instance2 = ModelWithEnum(name="Enum Test 2", user_type=UserType.GUEST)
    instance2.save()

    retrieved2 = ModelWithEnum.get_one(instance2.id)
    assert retrieved2.user_type == UserType.GUEST
    assert isinstance(retrieved2.user_type, UserType)
