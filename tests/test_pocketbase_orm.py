from datetime import datetime, timezone
from enum import Enum
import uuid

import pytest
import pytest_asyncio
from pocketbase import FileUpload
from pydantic import AnyUrl, EmailStr, Field

from pocketbase_orm import PBModel, User, PBReference, FileUploadORM


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
    image: FileUploadORM | None = Field(default=None, description="Image file upload")


class NonTypeChecksModel(PBModel, collection="non_type_checks"):
    name: str | None = None
    age: int | None = None
    is_active: bool | None = None
    tags: list[str] | None = None
    metadata: dict[str, str] | None = None
    time_field: datetime | None = None


class JSONTypeandFile(PBModel, collection="json_type_checks"):
    test_dict: dict | None = None
    test_list: list | None = None
    test_string_list: list[str] | None = None
    test_file: FileUploadORM | None = None
    test_file_2: FileUploadORM | None = None


class UserType(str, Enum):
    ADMIN = "admin"
    REGULAR = "regular"
    GUEST = "guest"


class ModelWithEnum(PBModel, collection="enum_models"):
    name: str
    user_type: UserType  # Using the actual enum type


class OptionalEnumModel(PBModel, collection="optional_enum_models"):
    name: str
    user_type: UserType | None = None


class ListEnumModel(PBModel, collection="list_enum_models"):
    name: str
    user_types: list[UserType]


class OptionalListEnumModel(PBModel, collection="optional_list_enum_models"):
    name: str
    user_types: list[UserType] | None = None


@pytest_asyncio.fixture(scope="function")
async def setup_models(pb_client):
    """Fixture to bind the client and sync collections."""
    PBModel.bind_client(pb_client)
    await User.sync_collection()
    await RelatedModel.sync_collection()
    await Example.sync_collection()
    await ModelWithEnum.sync_collection()
    await OptionalEnumModel.sync_collection()
    await ListEnumModel.sync_collection()
    await OptionalListEnumModel.sync_collection()
    await NonTypeChecksModel.sync_collection()
    await JSONTypeandFile.sync_collection()
    yield
    await ModelWithEnum.delete_collection()
    await OptionalEnumModel.delete_collection()
    await ListEnumModel.delete_collection()
    await OptionalListEnumModel.delete_collection()
    await Example.delete_collection()
    await RelatedModel.delete_collection()
    await NonTypeChecksModel.delete_collection()
    await JSONTypeandFile.delete_collection()


@pytest_asyncio.fixture(scope="function")
async def related_model(setup_models):
    """Fixture to create and return a test RelatedModel instance."""
    model = RelatedModel(name="Test Related Model")
    await model.save()
    yield model


@pytest.mark.asyncio
async def test_create_example_with_file(setup_models, related_model):
    """Test creating an Example record with a file upload."""
    with open("static/image.png", "rb") as f:
        example = Example(
            text_field="Test with image",
            number_field=123,
            is_active=True,
            email_field="test@example.com",
            url_field="http://example.com",  # type: ignore
            created_at=datetime.now(timezone.utc),
            options=["option1", "option2"],
            related_model=related_model.id,
            image=FileUpload(("image.png", f)),
        )
        await example.save()

        # Verify the record was created
        example_id = example.id
        assert example_id and example_id != ""

        # Test retrieval methods
        retrieved: Example = await Example.get_one(example_id)
        assert retrieved.text_field == "Test with image"
        assert retrieved.number_field == 123
        assert retrieved.is_active is True

        # Test list retrieval
        examples = await Example.get_full_list()
        assert len(examples) > 0
        assert any(e.id == example.id for e in examples)

        # Test filtering
        filtered = await Example.get_first_list_item(
            filter=f"email_field = '{example.email_field}'"
        )
        assert filtered.id

        # Test file contents
        image_bytes = await example.get_file_contents("image")
        assert len(image_bytes) > 0


@pytest.mark.asyncio
async def test_related_model_crud(setup_models):
    """Test CRUD operations for RelatedModel."""
    # Create
    model = RelatedModel(name="CRUD Test Model")
    await model.save()
    assert model.id != ""

    # Read
    retrieved = await RelatedModel.get_one(model.id)  # type: ignore
    assert retrieved.name == "CRUD Test Model"

    # Update
    model.name = "Updated Name"
    await model.save()
    updated = await RelatedModel.get_one(model.id)  # type: ignore
    assert updated.name == "Updated Name"

    # Delete
    await RelatedModel.delete_by_id(model.id)  # type: ignore
    with pytest.raises(Exception):
        await RelatedModel.get_one(model.id)  # type: ignore


def test_example_validation(setup_models, related_model):
    """Test validation rules for Example model."""
    # Test invalid email
    with pytest.raises(ValueError):
        Example(
            text_field="Test",
            number_field=123,
            is_active=True,
            email_field="invalid-email",  # type: ignore
            url_field="http://example.com",  # type: ignore
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
            url_field="invalid-url",  # type: ignore
            created_at=datetime.now(timezone.utc),
            options=["option1"],
            related_model=related_model.id,
        )


@pytest.mark.asyncio
async def test_get_list_pagination(setup_models, related_model):
    """Test pagination functionality of get_list method."""
    # Create multiple example records
    examples = []
    for i in range(1, 15):  # Create 15 records to test pagination
        example = Example(
            text_field=f"Test {i}",
            number_field=i,
            is_active=True,
            email_field=f"test{i}@example.com",
            url_field="http://example.com",  # type: ignore
            created_at=datetime.now(timezone.utc),
            options=["option1"],
            related_model=related_model.id,
        )
        await example.save()
        examples.append(example)

    # Test first page (5 items)
    page1 = await Example.get_list(page=1, per_page=5)
    print("Page 1 items:", page1)
    assert len(page1) == 5

    # Test second page (5 items)
    page2 = await Example.get_list(page=2, per_page=5)
    assert len(page2) == 5

    # Verify different records on different pages
    page1_ids = {item.id for item in page1}
    page2_ids = {item.id for item in page2}
    assert not page1_ids.intersection(page2_ids)  # No overlap between pages

    # Test with filter
    filtered = await Example.get_list(page=1, per_page=3, filter="number_field >= 10")
    assert len(filtered) == 3
    assert all(item.number_field >= 10 for item in filtered)


@pytest.mark.asyncio
async def test_user_collection_operations(setup_models):
    """Test that User model prevents collection creation/modification."""

    # Test that attempting to create users collection raises error
    with pytest.raises(RuntimeError) as exc_info:
        User._create_collection()
    assert "system collection" in str(exc_info.value)

    # Test that we can still create and work with User instances
    user = User(
        email="test@example.com", password="securepassword123", name="Test User"
    )
    assert user.email == "test@example.com"
    assert user.name == "Test User"


@pytest.mark.asyncio
async def test_user_crud_operations(setup_models):
    """Test CRUD operations for User model."""

    test_users: list[User] = []

    email = f"test.user{uuid.uuid4()}@example.com"

    # Test creating a user
    user = User(
        email=email,
        password="securepassword123",
        passwordConfirm="securepassword123",
        name="Test User",
        emailVisibility=True,
    )
    await user.save()
    assert user.id, "User should have an ID after saving"
    test_users.append(user)

    # Test get_one
    retrieved: User = await User.get_one(user.id)  # type: ignore
    assert retrieved.email == email
    assert retrieved.name == "Test User"
    assert retrieved.password is None  # Password should not be returned

    # Create more test users for list operations
    for i in range(1, 4):
        email = f"test.user{i}{uuid.uuid4()}@example.com"
        user = await User(
            email=email,
            password="securepassword123",
            passwordConfirm="securepassword123",
            name=f"Test User {i}",
        ).save()
        test_users.append(user)

    # Test get_list with pagination
    users_page = await User.get_list(page=1, per_page=2)
    assert len(users_page) == 2, "Should return 2 users per page"

    # Test get_full_list
    all_users = await User.get_full_list()
    assert len(all_users) >= len(test_users), "Should return all test users"

    first_user = await User.get_first_list_item(filter=f'email = "{email}"')
    assert first_user.email == email

    # Test updating a user
    user = test_users[0]
    user.name = "Updated Name"
    await user.save()

    updated: User = await User.get_one(user.id)
    assert updated.name == "Updated Name"

    for user in test_users:
        await user.delete()


@pytest.mark.asyncio
async def test_sync_collection_add_fields(pb_client):
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
            await InitialModel.delete_collection()
        except Exception as _:
            pass

        # 1. Create the collection with initial fields
        await InitialModel.sync_collection()

        # Verify the collection exists with expected fields
        collection = await pb_client.collections.get_one(collection_name)
        field_names = [field["name"] for field in collection["fields"]]

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
        await ExtendedModel.sync_collection()

        # Verify the collection now has the new fields
        updated_collection = await pb_client.collections.get_one(collection_name)
        updated_field_names = [field["name"] for field in updated_collection["fields"]]

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
            await InitialModel.delete_collection()
        except Exception as _:
            pass


@pytest.mark.asyncio
async def test_enum_field_handling(setup_models):
    """Test handling of enum fields in the model."""
    # Create an instance with an enum value
    instance = ModelWithEnum(name="Enum Test", user_type=UserType.ADMIN)
    await instance.save()

    # Retrieve the instance and check that it's converted to the proper enum type
    instance_id = instance.id
    assert instance_id and instance_id != ""
    retrieved = await ModelWithEnum.get_one(instance_id)
    assert retrieved.user_type == UserType.ADMIN
    assert isinstance(retrieved.user_type, UserType)  # Verify it's the actual enum type

    # Test with another enum value
    instance2 = ModelWithEnum(name="Enum Test 2", user_type=UserType.GUEST)
    await instance2.save()

    instance2_id = instance2.id
    assert instance2_id and instance2_id != ""
    retrieved2 = await ModelWithEnum.get_one(instance2_id)
    assert retrieved2.user_type == UserType.GUEST
    assert isinstance(retrieved2.user_type, UserType)


@pytest.mark.asyncio
async def test_optional_and_list_enums(setup_models):
    """Ensure optional and list enums are handled correctly."""
    opt = await OptionalEnumModel(name="Opt", user_type=UserType.REGULAR).save()
    fetched_opt = await OptionalEnumModel.get_one(opt.id)  # type: ignore
    assert fetched_opt.user_type == UserType.REGULAR
    opt_collection = await opt._pb_client.collections.get_one("optional_enum_models")
    opt_field = next(f for f in opt_collection["fields"] if f["name"] == "user_type")
    assert opt_field["maxSelect"] == 1
    assert opt_field["required"] is False

    list_model = await ListEnumModel(
        name="List", user_types=[UserType.ADMIN, UserType.GUEST]
    ).save()
    fetched_list = await ListEnumModel.get_one(list_model.id)  # type: ignore
    assert fetched_list.user_types == [UserType.ADMIN, UserType.GUEST]

    collection = await list_model._pb_client.collections.get_one("list_enum_models")
    field = next(f for f in collection["fields"] if f["name"] == "user_types")
    assert field["type"] == "select"
    assert field["maxSelect"] == len(UserType)


@pytest.mark.asyncio
async def test_optional_list_enum_model(setup_models):
    """Ensure optional list of enums works."""
    model = await OptionalListEnumModel(name="OptListNone").save()
    fetched = await OptionalListEnumModel.get_one(model.id)  # type: ignore
    assert fetched.user_types == []
    collection = await model._pb_client.collections.get_one("optional_list_enum_models")
    field = next(f for f in collection["fields"] if f["name"] == "user_types")
    assert field["required"] is False
    assert field["maxSelect"] == len(UserType)

    model2 = await OptionalListEnumModel(
        name="OptListVal", user_types=[UserType.REGULAR]
    ).save()
    fetched2 = await OptionalListEnumModel.get_one(model2.id)  # type: ignore
    assert fetched2.user_types == [UserType.REGULAR]


@pytest.mark.asyncio
async def test_non_type_checks_model(setup_models):
    """Test model that allows non-type checks."""
    model = NonTypeChecksModel()
    await model.save()

    # Verify the record was created
    assert model.id and model.id != ""

    # Retrieve and check fields
    retrieved: NonTypeChecksModel = await NonTypeChecksModel.get_one(model.id)  # type: ignore
    assert retrieved.name is None
    assert retrieved.age == 0
    assert retrieved.is_active is False
    assert retrieved.tags is None
    assert retrieved.metadata is None
    assert retrieved.time_field is None


@pytest.mark.asyncio
async def test_json_type_checks_model(setup_models):
    """Test model with JSON type checks."""
    model = JSONTypeandFile(
        test_dict={"key1": "value1", "key2": "value2"},
        test_list=["item1", "item2"],
        test_string_list=["string1", "string2"],
        test_file=FileUpload(("test_file.txt", b"Test file content")),
    )
    await model.save()

    # Verify the record was created
    assert model.id and model.id != ""

    # Retrieve and check fields
    retrieved: JSONTypeandFile = await JSONTypeandFile.get_one(model.id)  # type: ignore
    assert retrieved.test_dict == {"key1": "value1", "key2": "value2"}
    assert retrieved.test_list == ["item1", "item2"]
    assert retrieved.test_string_list == ["string1", "string2"]
