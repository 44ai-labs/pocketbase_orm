import pytest
import pytest_asyncio
from pydantic import Field

from pocketbase_orm import PBModel


class ExtraModel(PBModel, collection="extra_models"):
    name: str | None = Field(default=None, json_schema_extra={"min": 2})


class PresentableModel(PBModel, collection="presentable_models"):
    """Model used to test the presentable option in json_schema_extra."""

    invisible: str | None = Field(
        default=None, json_schema_extra={"presentable": False}
    )
    visible: str | None = Field(default=None, json_schema_extra={"presentable": True})


@pytest_asyncio.fixture(scope="function")
async def setup_extra_model(pb_client):
    PBModel.bind_client(pb_client)
    await ExtraModel.sync_collection()
    yield
    await ExtraModel.delete_collection()


@pytest_asyncio.fixture(scope="function")
async def setup_presentable_model(pb_client):
    """Bind client and sync PresentableModel collection."""
    PBModel.bind_client(pb_client)
    await PresentableModel.sync_collection()
    yield
    await PresentableModel.delete_collection()


@pytest.mark.asyncio
async def test_json_schema_extra_applied(setup_extra_model):
    collection = await ExtraModel._pb_client.collections.get_one("extra_models")
    fields = collection["fields"]
    name_field = next((f for f in fields if f["name"] == "name"), None)
    assert name_field is not None
    assert name_field.get("min") == 2


@pytest.mark.asyncio
async def test_presentable_option_applied(setup_presentable_model):
    """Ensure the presentable flag can be set via json_schema_extra."""
    collection = await PresentableModel._pb_client.collections.get_one(
        "presentable_models"
    )
    fields = {f["name"]: f for f in collection["fields"]}
    assert fields["invisible"].get("presentable") is False
    assert fields["visible"].get("presentable") is True
