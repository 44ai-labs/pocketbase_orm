import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, TypeVar, Generic, get_origin, get_args, Type
import typing
import types

import httpx
from pocketbase import PocketBase, FileUpload
from pocketbase.services.record import RecordService
from pocketbase.models.dtos import CollectionModel, Record
from pydantic import AnyUrl, BaseModel, EmailStr, Field

__version__ = "0.17.2"

logger = logging.getLogger(__name__)

T = TypeVar("T", bound="PBModel")


class PBReferenceType(Generic[T]):
    """
    A generic type hint to signify a reference to another model type T.
    This class itself doesn't need to be a Pydantic model if it's purely for type hinting.
    """

    pass


PBReference = (
    PBReferenceType[T] | str
)  # has to be string to set it correctly when writing a relation id


def _pluralize(singular: str) -> str:
    """Simple English pluralization."""
    if singular.endswith("y"):
        return singular[:-1] + "ies"
    elif singular.endswith(("s", "sh", "ch", "x", "z")):
        return singular + "es"
    else:
        return singular + "s"


class PBModel(BaseModel):
    """
    Base model class for all PocketBase models.
    Provides methods for schema synchronization and querying the PocketBase database.
    """

    id: str | None = None
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        str_strip_whitespace = True
        str_min_length = 1
        arbitrary_types_allowed = True

    def __init_subclass__(cls, *, collection: str | None = None, **kwargs):
        """
        Initialize subclass with optional collection name.
        If collection name is not provided, it will be derived from the class name.
        """
        super().__init_subclass__(**kwargs)
        if collection is not None:
            cls._collection_name = collection
        else:
            cls._collection_name = _pluralize(cls.__name__.lower())

    @classmethod
    def bind_client(cls, client: PocketBase):
        """
        Bind the PocketBase client to the model class.
        """
        cls._pb_client = client

    @classmethod
    async def init_client(
        cls,
        url: str,
        admin_email: str | None = None,
        admin_password: str | None = None,
    ) -> PocketBase:
        """
        Initialize a PocketBase client and bind it to the model class.

        Args:
            url: The PocketBase server URL
            admin_email: Optional admin email for authentication
            admin_password: Optional admin password for authentication

        Returns:
            The initialized PocketBase client

        Example:
            client = PBModel.init_client("http://127.0.0.1:8090", "admin@example.com", "password")
        """
        client = PocketBase(url)
        if admin_email and admin_password:
            await client.collection("_superusers").auth.with_password(
                admin_email, admin_password
            )
        cls.bind_client(client)
        return client

    @classmethod
    def get_collection_name(cls) -> str:
        """
        Get the collection name for the model.
        Returns the collection name specified during class creation or derived from class name.
        """
        return cls._collection_name

    @classmethod
    def get_collection(cls) -> RecordService:
        """
        Returns the collection instance for the model.
        """
        if not hasattr(cls, "_pb_client") or cls._pb_client is None:
            raise RuntimeError(
                "PocketBase client not bound. Call PBModel.bind_client() first."
            )
        return cls._pb_client.collection(cls.get_collection_name())

    @classmethod
    async def delete_by_id(cls, id: str, *args, **kwargs):
        """Delete a record from the collection by ID."""
        return await cls.get_collection().delete(id, *args, **kwargs)

    async def delete(self, id=None, *args, **kwargs):
        """Delete this record instance from the collection."""
        return await self.get_collection().delete(id or self.id, *args, **kwargs)

    @classmethod
    async def delete_collection(cls):
        """
        Delete the entire collection from PocketBase.

        Raises:
            RuntimeError: If PocketBase client is not bound
            Exception: If deletion fails or collection doesn't exist
        """
        if not hasattr(cls, "_pb_client") or cls._pb_client is None:
            raise RuntimeError(
                "PocketBase client not bound. Call PBModel.bind_client() first."
            )

        collection_name = cls.get_collection_name()
        try:
            # Get collection ID first
            collection = await cls._pb_client.collections.get_one(collection_name)
            # Delete the collection
            await cls._pb_client.collections.delete(collection["id"])
            logger.debug(f"Collection {collection_name} deleted successfully.")
        except Exception as e:
            if "404" in str(e):
                logger.warning(f"Collection {collection_name} does not exist.")
            else:
                logger.error(f"Error deleting collection {collection_name}: {e}")
                raise

    def is_union_type(field_type: Any) -> bool:
        origin = typing.get_origin(field_type)
        return origin is typing.Union or origin is types.UnionType

    @classmethod
    def is_file_upload_union(cls, field_type):
        args = get_args(field_type)
        return (
            cls.is_union_type(field_type) and FileUpload in args
        ) or field_type is FileUpload

    @classmethod
    def _process_record_data(cls, record_data: Record) -> Dict[str, Any]:
        """
        Process record data before model validation.
        Handles special cases like file fields.
        """
        processed_data = record_data.copy()

        # Get field types from annotations
        for field_name, field_type in cls.__annotations__.items():
            if field_name not in processed_data:
                continue

            # Check if field is a file type (in a Union)
            is_file_field = cls.is_file_upload_union(field_type)

            # Handle file fields - convert empty strings to None
            if is_file_field and processed_data[field_name] == "":
                processed_data[field_name] = None

        return processed_data

    @classmethod
    async def get_one(cls, id: str, **kwargs) -> T:
        """Get a single record from the collection and convert to model instance."""
        record = await cls.get_collection().get_one(id, kwargs)
        processed_data = cls._process_record_data(record)
        return cls.model_validate(processed_data)

    @classmethod
    async def get_list(cls, page: int = 1, per_page: int = 10, **kwargs) -> list[T]:
        """Get a list of records from the collection and convert to model instances."""
        results = await cls.get_collection().get_list(page, per_page, kwargs)
        items = [
            cls.model_validate(cls._process_record_data(record))
            for record in results["items"]
        ]
        return items

    @classmethod
    async def get_full_list(cls, **kwargs) -> list[T]:
        """Get a full list of records and convert to model instances."""
        records = await cls.get_collection().get_full_list(**kwargs)
        return [
            cls.model_validate(cls._process_record_data(record)) for record in records
        ]

    @classmethod
    async def get_first_list_item(cls, **kwargs) -> T:
        """Get the first matching record and convert to model instance."""
        record = await cls.get_collection().get_first(kwargs)
        processed_data = cls._process_record_data(record)
        return cls.model_validate(processed_data)

    @classmethod
    async def sync_collection(cls):
        """
        Sync the collection schema with PocketBase. Will create or update the collection.
        """
        collection_name = cls.get_collection_name()

        try:
            existing_collection = await cls._pb_client.collections.get_one(
                collection_name
            )
            logger.debug(f"Collection {collection_name} exists. Updating schema...")
            await cls._update_collection(existing_collection)
        except Exception as e:
            if "404" in str(e):  # Only create if collection doesn't exist
                logger.debug(
                    f"Collection {collection_name} does not exist. Creating collection..."
                )
                await cls._create_collection()
            else:
                logger.error(f"Error syncing collection: {e}")
                raise

    @classmethod
    async def _create_collection(cls):
        """
        Create the collection schema in PocketBase.
        """
        fields = await cls._generate_fields()
        collection_name = cls.get_collection_name()

        collection_payload = {
            "name": collection_name,
            "type": "base",
            "fields": fields,
        }

        logger.debug(f"Creating collection with payload: {collection_payload}")

        try:
            response = await cls._pb_client.collections.create(collection_payload)
            logger.debug(f"Collection {collection_name} created successfully.")
            return response
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            # Try to get more details about the error
            if hasattr(e, "response") and hasattr(e.response, "json"):
                try:
                    error_details = e.response.json()  # type: ignore
                    logger.error(f"Error details: {error_details}")
                except Exception as _:
                    pass
            raise

    @classmethod
    async def _update_collection(cls, existing_collection: CollectionModel):
        """
        Update the collection schema in PocketBase.
        """
        # Get the schema from the existing collection
        current_fields = {
            field["name"]: field for field in existing_collection["fields"]
        }
        new_fields = await cls._generate_fields()
        all_fields = {field["name"]: field for field in new_fields}

        # Preserve existing fields and add new ones
        final_fields = []
        for field in existing_collection["fields"]:
            if field["name"] not in all_fields:
                # the field will be removed
                continue
            logger.debug(f"Processing field {field['name']}")
            # https://github.com/44ai-labs/pocketbase/blob/01be3cc23726335b1cf28f5f4f30ffa30feb256c/pocketbase/models/utils/collection_field.py
            field_dict = {
                "name": field["name"],
                "type": field["type"],
                "required": field["required"] if "required" in field else False,
                "system": field["system"],
                "onCreate": field["onCreate"] if "onCreate" in field else False,
                "onUpdate": field["onUpdate"] if "onUpdate" in field else False,
            }
            if hasattr(field, "options") and field["options"]:
                field_dict["options"] = field["options"]
            # make sure we sync references correct
            field_name = field["name"]
            for new_field in new_fields:
                if new_field["name"] == field_name:
                    field_dict.update(new_field)
            final_fields.append(field_dict)

        # Add new fields that don't exist yet
        for new_field in new_fields:
            if new_field["name"] not in current_fields:
                final_fields.append(new_field)

        try:
            logger.debug(
                f"UPDATING {existing_collection['id']}, {existing_collection['name']}, {final_fields}"
            )
            await cls._pb_client.collections.update(
                existing_collection["id"],
                {
                    "name": existing_collection["name"],
                    "fields": final_fields,
                },
            )
            logger.debug(
                f"Collection {existing_collection['name']} updated successfully."
            )
        except Exception as e:
            logger.error(f"Error updating collection: {e}")
            raise

    @staticmethod
    def get_referenced_pbmodel_type(ref_type_hint: Any) -> Type["PBModel"] | None:
        if get_origin(ref_type_hint) is PBReferenceType:
            args = get_args(ref_type_hint)
            if args and isinstance(args[0], type) and issubclass(args[0], PBModel):
                return args[0]
        return None

    @classmethod
    async def _generate_fields(cls) -> list[Dict[str, Any]]:
        """
        Generate the field definitions for the collection based on the Pydantic model.
        """
        fields = []
        model_fields = cls.model_fields

        logger.debug(f"Generating fields for {cls.__name__}")

        # Add fields for created and updated
        fields.extend(
            [
                {
                    "hidden": False,
                    "name": "created",
                    "onCreate": True,
                    "onUpdate": False,
                    "presentable": False,
                    "system": False,
                    "type": "autodate",
                },
                {
                    "hidden": False,
                    "name": "updated",
                    "onCreate": True,
                    "onUpdate": True,
                    "presentable": False,
                    "system": False,
                    "type": "autodate",
                },
            ]
        )

        for name, field in cls.__annotations__.items():
            if name in ["id", "created", "updated"]:  # Skip base model fields
                continue

            field_def = {"name": name, "type": cls._get_field_type(field)}
            logger.debug(f"Processing field {name} with type {field_def['type']}")

            # Get field info from Pydantic model
            field_info = model_fields[name]
            field_def["required"] = field_info.is_required()

            # Configure enum select field options if applicable
            let_enum = None
            if hasattr(field, "__origin__") and cls.is_union_type(field):
                for arg in field.__args__:
                    if isinstance(arg, type) and issubclass(arg, Enum):
                        let_enum = arg
                        break
            elif isinstance(field, type) and issubclass(field, Enum):
                let_enum = field

            if let_enum is not None and field_def["type"] == "select":
                field_def.update(
                    {
                        "maxSelect": 1,
                        "values": [e.value for e in let_enum],
                    }
                )
                logger.debug(f"Configured enum select field {name} with: {field_def}")

            # Add additional configuration for relation fields
            if field_def["type"] == "relation":
                logger.debug(f"Configuring relation field {name}")
                # Find the related model in Union types
                related_model = None
                if hasattr(field, "__origin__") and cls.is_union_type(field):
                    for arg in field.__args__:
                        if arg is str:
                            continue
                        if cls._is_reference_type(arg):
                            print(f"Found reference type for {name}: {arg}")
                            releated_model = cls.get_referenced_pbmodel_type(arg)
                            if releated_model:
                                related_model = releated_model
                                logger.debug(
                                    f"Found related model for {name}: {related_model}"
                                )
                            break
                if related_model:
                    try:
                        logger.debug(
                            f"Looking up collection for {related_model.get_collection_name()}"
                        )
                        collection = await cls._pb_client.collections.get_one(
                            related_model.get_collection_name()
                        )
                        logger.debug(f"Found collection for {name}: {collection['id']}")

                        field_def.update(
                            {
                                "name": name,
                                "type": "relation",
                                "system": False,
                                "required": field_info.is_required(),
                                "presentable": False,
                                "cascadeDelete": False,
                                "minSelect": 0,
                                "maxSelect": 1,
                                "collectionId": collection[
                                    "id"
                                ],  # This must be present and non-empty
                            }
                        )

                        logger.debug(f"Field definition for {name}: {field_def}")
                    except Exception as e:
                        logger.error(
                            f"Error getting collection ID for {related_model.get_collection_name()}: {e}",
                            exc_info=True,
                        )
                        raise
                else:
                    logger.error(f"No valid related model found for field {name}")
                    raise ValueError(f"Invalid relation configuration for field {name}")

            fields.append(field_def)
            logger.debug(f"Added field definition: {field_def}")

        logger.debug(f"Final fields configuration: {fields}")
        return fields

    @staticmethod
    def _is_enum_type(field_type: Any) -> bool:
        """Check if a type is an Enum subclass."""
        return isinstance(field_type, type) and issubclass(field_type, Enum)

    @staticmethod
    def _is_reference_type(field_type: type) -> bool:
        """Check if a type is a PBModel subclass."""
        origin = get_origin(field_type)
        if origin is PBReferenceType:
            return True
        if field_type is PBReferenceType:
            return True
        return False

    @classmethod
    def _get_field_type(cls, pydantic_field: Any) -> str:
        """
        Convert the Pydantic field type into a PocketBase field type.
        """
        # Get all possible types to check
        types_to_check = []
        if hasattr(pydantic_field, "__origin__"):
            if cls.is_union_type(pydantic_field):
                types_to_check.extend(pydantic_field.__args__)
            elif pydantic_field.__origin__ is list:
                return "json"
        elif hasattr(pydantic_field, "__or__") and hasattr(pydantic_field, "__args__"):
            types_to_check.extend(pydantic_field.__args__)
        else:
            types_to_check.append(pydantic_field)

        # Check all types in priority order
        for field_type in types_to_check:
            # Special types
            if PBModel._is_enum_type(field_type):
                return "select"
            if PBModel._is_reference_type(field_type):
                return "relation"
            if field_type == FileUpload:
                return "file"

            # Basic types
            if field_type is str:
                return "text"
            if field_type in (int, float):
                return "number"
            if field_type is bool:
                return "bool"
            if field_type == EmailStr:
                return "email"
            if field_type == AnyUrl:
                return "url"
            if field_type == datetime:
                return "date"
            if isinstance(field_type, (list, dict)):
                return "json"

        # Default to json for complex types
        return "json"

    async def save(self) -> T:
        """
        Save the model instance to PocketBase.
        """
        collection = self.get_collection()

        # Prepare data for saving - handle file uploads specially
        data = {}
        for field_name, field_info in self.model_fields.items():
            if field_name in ("created", "updated"):
                continue

            field_value = getattr(self, field_name)
            if field_value is None:
                continue

            if isinstance(field_value, FileUpload):
                # Keep FileUpload objects as-is
                data[field_name] = field_value
            else:
                # For non-file fields, use model_dump to handle serialization
                try:
                    data[field_name] = self.model_dump(
                        include={field_name}, mode="json"
                    )[field_name]
                except Exception as e:
                    logger.warning(f"Error serializing field {field_name}: {e}")
                    data[field_name] = field_value

        if hasattr(self, "id") and self.id:
            result = await collection.update(self.id, data)
            logger.debug(f"Updated record with ID: {self.id}")
        else:
            result = await collection.create(data)
            self.id = result["id"]
            logger.debug(f"Created new record with ID: {self.id}")

        print("Record, result:", result)
        # Update instance with response data from PocketBase
        self.created = result.get("created", self.created)
        self.updated = result.get("updated", self.updated)

        return self

    async def get_file_contents(self, field: str) -> bytes:
        """
        Get the contents of a file field using httpx.

        Args:
            field: Name of the file field

        Returns:
            bytes: The file contents

        Raises:
            ValueError: If the field doesn't exist or isn't a file field
            RuntimeError: If there's an error fetching the file
        """
        # Get the field value
        field_value = getattr(self, field)
        if not field_value:
            raise ValueError(f"No file exists in field '{field}'")

        # If it's a FileUpload object, return the file contents directly
        if isinstance(field_value, FileUpload):
            # Get the file object from the FileUpload
            # FileUpload.files is a tuple where the second element is the file
            _, file_obj = field_value.files[0]
            # Seek to start in case file was already read
            file_obj.seek(0)
            return file_obj.read()

        # Otherwise, treat it as a filename and fetch from PocketBase
        client = self._pb_client
        if not client:
            raise RuntimeError(
                "PocketBase client not bound. Call PBModel.bind_client() first."
            )
        collection_name = self.get_collection_name()

        # Construct the PocketBase file URL
        file_url = f"{client._inners.client.base_url}/api/files/{collection_name}/{self.id}/{field_value}"

        try:
            response = httpx.get(file_url)
            response.raise_for_status()
            return response.content
        except Exception as e:
            raise RuntimeError(f"Error fetching file contents: {e}")


class User(PBModel, collection="users"):
    """Model class for PocketBase's built-in users collection."""

    email: EmailStr
    password: str | None = None  # Only used when creating/updating
    passwordConfirm: str | None = None  # Required when creating/updating password
    emailVisibility: bool = False
    verified: bool = False
    name: str | None = Field(default=None, min_length=0)
    avatar: FileUpload | None = None

    @classmethod
    def _create_collection(cls):
        """Override to prevent creation of system collection."""
        raise RuntimeError(
            "Cannot create or modify the users collection as it is a system collection."
        )

    @classmethod
    def _update_collection(cls, existing_collection):
        """Override to prevent modification of system collection."""
        raise RuntimeError(
            "Cannot create or modify the users collection as it is a system collection."
        )
