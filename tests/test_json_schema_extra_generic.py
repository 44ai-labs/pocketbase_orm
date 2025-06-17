import pytest
import pytest_asyncio
from pydantic import Field

from pocketbase_orm import PBModel


class ExtraModel(PBModel, collection="extra_models"):
    name: str | None = Field(default=None, json_schema_extra={"min": 2})


@pytest_asyncio.fixture(scope="function")
async def setup_extra_model(pb_client):
    PBModel.bind_client(pb_client)
    await ExtraModel.sync_collection()
    yield
    await ExtraModel.delete_collection()


@pytest.mark.asyncio
async def test_json_schema_extra_applied(setup_extra_model):
    collection = await ExtraModel._pb_client.collections.get_one("extra_models")  # type: ignore
    fields = collection["fields"]
    name_field = next((f for f in fields if f["name"] == "name"), None)
    assert name_field is not None
    assert name_field.get("min") == 2
