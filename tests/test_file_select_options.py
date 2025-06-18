import pytest
import pytest_asyncio
from pocketbase_orm import PBModel
from pocketbase import FileUpload


class FileSelectModel(PBModel, collection="file_select_models"):
    required_file: FileUpload
    optional_file: FileUpload | None = None
    multi_files: list[FileUpload] = []


@pytest_asyncio.fixture(scope="function")
async def setup_file_select_model(pb_client):
    PBModel.bind_client(pb_client)
    await FileSelectModel.sync_collection()
    yield
    # await FileSelectModel.delete_collection()


@pytest.mark.asyncio
async def test_file_select_min_max(setup_file_select_model):
    collection = await FileSelectModel._pb_client.collections.get_one(  # type: ignore
        "file_select_models"
    )
    fields = {f["name"]: f for f in collection["fields"]}
    assert fields["optional_file"].get("maxSelect") == 1
    assert fields["required_file"].get("maxSelect") == 1
    assert fields["multi_files"].get("maxSelect") == 99
