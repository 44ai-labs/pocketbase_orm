from pocketbase_orm import PBModel, User, PBReference
import time


class Addon(PBModel, collection="addons"):
    name: str
    description: str
    user: PBReference[User]
    tags: list[str]
    price: float
    is_active: bool


class Addon1(PBModel, collection="test_addons"):
    name: str
    description: str
    user: PBReference[User]
    tags: list[str]
    price: float
    is_active: bool
    test: PBReference[Addon]
    test2: PBReference[Addon]


class Addon2(PBModel, collection="test_addons_2"):
    name: str
    description: str
    user: PBReference[User]
    tags: list[str]
    price: float
    is_active: bool
    test: PBReference[Addon1]
    test2: PBReference[Addon1]


def test_collections_resync(pb_client):
    PBModel.bind_client(pb_client)
    Addon.sync_collection()
    time.sleep(
        1
    )  # we need one second sleep as filenames from pocketbase have second timestamps
    Addon1.sync_collection()
    time.sleep(1)
    Addon2.sync_collection()
    time.sleep(1)
    # resync collections
    Addon2.sync_collection()
    time.sleep(1)
    Addon.sync_collection()
    time.sleep(1)
    Addon2.delete_collection()
    time.sleep(1)
    Addon2.sync_collection()
    time.sleep(1)

    # remove a field from the model
    class Addon2Removed(PBModel, collection="test_addons_2"):
        name: str
        description: str
        user: PBReference[User]
        tags: list[str]
        is_active: bool
        test2: PBReference[Addon1]

    Addon2Removed.sync_collection()
    time.sleep(1)
    Addon2Removed.sync_collection()

    # we could add check here that looks at `pb_migrations` folder
