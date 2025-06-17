import uuid
import pytest
import pytest_asyncio
from pocketbase_orm import PBModel, PBReference, User


class SingleOptional(PBModel, collection="single_optional"):
    name: str
    user: PBReference[User] | None = None


class MultiRef(PBModel, collection="multi_ref"):
    name: str
    users: list[PBReference[User]]


class MultiOptional(PBModel, collection="multi_optional"):
    name: str
    users: list[PBReference[User]] | None = None


@pytest_asyncio.fixture(scope="function")
async def setup_reference_models(pb_client):
    PBModel.bind_client(pb_client)
    await SingleOptional.sync_collection()
    await MultiRef.sync_collection()
    await MultiOptional.sync_collection()
    yield
    await SingleOptional.delete_collection()
    await MultiRef.delete_collection()
    await MultiOptional.delete_collection()


@pytest.mark.asyncio
async def test_reference_types(setup_reference_models, pb_client):
    user = await User(
        email=f"test.{uuid.uuid4()}@example.com",
        password="password123",
        passwordConfirm="password123",
        name="Tester",
    ).save()

    single = SingleOptional(name="s", user=user.id)
    await single.save()
    retrieved_single = await SingleOptional.get_one(single.id)  # type: ignore
    assert retrieved_single.user == user.id

    multi = MultiRef(name="m", users=[user.id])
    await multi.save()
    retrieved_multi = await MultiRef.get_one(multi.id)  # type: ignore
    assert retrieved_multi.users == [user.id]

    multi_opt = MultiOptional(name="o", users=[user.id])
    await multi_opt.save()
    retrieved_multi_opt = await MultiOptional.get_one(multi_opt.id)  # type: ignore
    assert retrieved_multi_opt.users == [user.id]

    col = await pb_client.collections.get_one("multi_ref")
    field = next(f for f in col["fields"] if f["name"] == "users")
    assert field.get("maxSelect", 0) == 0

    col_single = await pb_client.collections.get_one("single_optional")
    field_single = next(f for f in col_single["fields"] if f["name"] == "user")
    assert field_single.get("maxSelect", 1) == 1

    await user.delete()
