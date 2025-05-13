from pocketbase_orm import PBModel, User, PBReference


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
    Addon2.sync_collection()
    Addon2.sync_collection()
    # resync collections
    Addon2.sync_collection()
    Addon.sync_collection()
    Addon2.delete_collection()
    Addon2.sync_collection()
    # we could add check here that looks at `pb_migrations` folder
