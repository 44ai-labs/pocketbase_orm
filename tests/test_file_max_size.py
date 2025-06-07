import pytest
import pytest_asyncio
from pydantic import Field

from pocketbase_orm import PBModel, FileUploadORM


class FileModelWithMaxSize(PBModel, collection="file_max_size_models"):
    title: str
    # 5MB max file size
    attachment: FileUploadORM | None = Field(
        None,
        json_schema_extra={"maxSize": 441944194419},
    )


@pytest_asyncio.fixture(scope="function")
async def setup_file_max_size_model(pb_client):
    """Fixture to bind the client and sync collection."""
    PBModel.bind_client(pb_client)
    await FileModelWithMaxSize.sync_collection()
    yield
    await FileModelWithMaxSize.delete_collection()


@pytest.mark.asyncio
async def test_file_upload_max_size(setup_file_max_size_model):
    """Test that maxSize parameter is properly set in PocketBase schema."""
    # Create a test instance
    model = FileModelWithMaxSize(title="Test Max Size")
    await model.save()

    # Fetch the collection to check if maxSize is set
    collection = await model._pb_client.collections.get_one("file_max_size_models")
    fields = collection["fields"]
    attachment_field = next((f for f in fields if f["name"] == "attachment"), None)
    assert attachment_field is not None, (
        "Attachment field should exist in the collection schema"
    )

    print(attachment_field)
    assert attachment_field["maxSize"] == 441944194419
