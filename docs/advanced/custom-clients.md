# Custom Clients

Patterns for creating custom Azure clients by subclassing the library's base classes.

## Subclassing Patterns

### Domain-Specific Cosmos Client

```python
from aio_azure_clients_toolbox import ManagedCosmos
from azure.core import MatchConditions
from datetime import datetime
import uuid

class UserRepository(ManagedCosmos):
    """Domain-specific repository for user management."""

    def __init__(self, config):
        super().__init__(
            endpoint=config.cosmos_endpoint,
            dbname=config.cosmos_database,
            container_name="users",
            credential=config.get_credential()
        )

    async def create_user(self, user_data: dict) -> dict:
        """Create a new user with automatic ID and timestamp generation."""
        user_document = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "version": 1,
            **user_data
        }

        async with self.get_container_client() as container:
            return await container.create_item(body=user_document)

    async def get_user(self, user_id: str) -> dict | None:
        """Get user by ID, return None if not found."""
        try:
            async with self.get_container_client() as container:
                return await container.read_item(
                    item=user_id,
                    partition_key=user_id
                )
        except exceptions.CosmosResourceNotFoundError:
            return None

    async def update_user(self, user_id: str, updates: dict,
                         etag: str = None) -> dict:
        """Update user with optimistic concurrency control."""
        async with self.get_container_client() as container:
            # Read current document
            current = await container.read_item(
                item=user_id,
                partition_key=user_id
            )

            # Apply updates
            updated_doc = {
                **current,
                **updates,
                "updated_at": datetime.utcnow().isoformat(),
                "version": current.get("version", 1) + 1
            }

            # Replace with etag check if provided
            if etag:
                return await container.replace_item(
                    item=user_id,
                    body=updated_doc,
                    match_condition=MatchConditions.IfNotModified,
                    etag=etag
                )
            else:
                return await container.replace_item(
                    item=user_id,
                    body=updated_doc
                )

    async def find_users_by_email(self, email: str) -> list[dict]:
        """Find users by email address."""
        query = "SELECT * FROM users u WHERE u.email = @email"
        parameters = [{"name": "@email", "value": email}]

        async with self.get_container_client() as container:
            items = []
            async for user in container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                items.append(user)
            return items

    async def find_active_users(self, limit: int = 100) -> list[dict]:
        """Find recently active users."""
        query = """
        SELECT * FROM users u
        WHERE u.last_login_at > @cutoff_date
        ORDER BY u.last_login_at DESC
        OFFSET 0 LIMIT @limit
        """

        cutoff_date = (datetime.utcnow() - timedelta(days=30)).isoformat()
        parameters = [
            {"name": "@cutoff_date", "value": cutoff_date},
            {"name": "@limit", "value": limit}
        ]

        async with self.get_container_client() as container:
            items = []
            async for user in container.query_items(
                query=query,
                parameters=parameters
            ):
                items.append(user)
            return items
```

### Document Storage Client

```python
import tempfile
import os
import aiofiles
from aio_azure_clients_toolbox import AzureBlobStorageClient
from azure.storage.blob import BlobSasPermissions
from datetime import datetime, timedelta

class DocumentStorageClient(AzureBlobStorageClient):
    """Enhanced blob storage client for document management."""

    CONTAINER_NAME = "documents"
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt"}
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

    def __init__(self, storage_url: str, credential, workspace_dir: str = "/tmp"):
        super().__init__(storage_url, self.CONTAINER_NAME, credential)
        self.workspace_dir = workspace_dir

    async def upload_document(self, file_path: str, content: bytes,
                            metadata: dict = None) -> dict:
        """Upload document with validation and metadata."""

        # Validate file extension
        _, ext = os.path.splitext(file_path)
        if ext.lower() not in self.ALLOWED_EXTENSIONS:
            raise ValueError(f"File extension {ext} not allowed")

        # Validate file size
        if len(content) > self.MAX_FILE_SIZE:
            raise ValueError(f"File size exceeds {self.MAX_FILE_SIZE} bytes")

        # Add metadata
        document_metadata = {
            "uploaded_at": datetime.utcnow().isoformat(),
            "file_size": str(len(content)),
            "file_extension": ext.lower(),
            **(metadata or {})
        }

        # Upload with metadata
        async with self.get_blob_client(file_path) as blob_client:
            result = await blob_client.upload_blob(
                content,
                overwrite=True,
                metadata=document_metadata
            )

        return {
            "path": file_path,
            "size": len(content),
            "metadata": document_metadata,
            "etag": result["etag"]
        }

    async def download_document_to_workspace(self, file_path: str) -> str:
        """Download document to temporary workspace."""

        # Create temporary directory
        tempdir = tempfile.mkdtemp(dir=self.workspace_dir)
        filename = os.path.basename(file_path)
        local_path = os.path.join(tempdir, filename)

        # Stream download to avoid memory issues
        async with aiofiles.open(local_path, "wb") as file:
            async with self.get_blob_client(file_path) as blob_client:
                stream = await blob_client.download_blob()
                async for chunk in stream.chunks():
                    await file.write(chunk)

        return local_path

    async def get_document_info(self, file_path: str) -> dict:
        """Get document metadata and properties."""
        async with self.get_blob_client(file_path) as blob_client:
            properties = await blob_client.get_blob_properties()

            return {
                "path": file_path,
                "size": properties.size,
                "last_modified": properties.last_modified.isoformat(),
                "etag": properties.etag,
                "content_type": properties.content_settings.content_type,
                "metadata": properties.metadata or {}
            }

    async def create_temporary_access_url(self, file_path: str,
                                        hours: int = 24) -> str:
        """Create temporary read-only access URL."""
        return await self.get_blob_sas_url(
            file_path,
            permission=BlobSasPermissions(read=True),
            expiry_hours=hours
        )

    async def create_upload_url(self, file_path: str, hours: int = 1) -> str:
        """Create temporary upload URL for direct client uploads."""
        return await self.get_blob_sas_url(
            file_path,
            permission=BlobSasPermissions(write=True, create=True),
            expiry_hours=hours
        )

    async def list_documents(self, prefix: str = None) -> list[dict]:
        """List documents with metadata."""
        documents = []

        async with self.get_blob_service_client() as service_client:
            container_client = service_client.get_container_client(self.CONTAINER_NAME)

            async for blob in container_client.list_blobs(
                name_starts_with=prefix,
                include=["metadata"]
            ):
                documents.append({
                    "path": blob.name,
                    "size": blob.size,
                    "last_modified": blob.last_modified.isoformat(),
                    "metadata": blob.metadata or {}
                })

        return documents
```

### Event Publishing Client

```python
from aio_azure_clients_toolbox.clients.eventgrid import EventGridClient
import json
from datetime import datetime
from typing import Any

class DomainEventPublisher:
    """Domain-specific event publishing with automatic enrichment."""

    def __init__(self, eventgrid_client: EventGridClient, service_name: str):
        self.client = eventgrid_client
        self.service_name = service_name

    async def publish_user_event(self, event_type: str, user_id: str,
                               data: dict, correlation_id: str = None):
        """Publish user domain events."""
        await self._publish_domain_event(
            domain="user",
            event_type=event_type,
            entity_id=user_id,
            data=data,
            correlation_id=correlation_id
        )

    async def publish_order_event(self, event_type: str, order_id: str,
                                data: dict, correlation_id: str = None):
        """Publish order domain events."""
        await self._publish_domain_event(
            domain="order",
            event_type=event_type,
            entity_id=order_id,
            data=data,
            correlation_id=correlation_id
        )

    async def _publish_domain_event(self, domain: str, event_type: str,
                                  entity_id: str, data: dict,
                                  correlation_id: str = None):
        """Publish enriched domain event."""

        enriched_data = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "source_service": self.service_name,
            "domain": domain,
            "entity_id": entity_id,
            "occurred_at": datetime.utcnow().isoformat(),
            "schema_version": "1.0",
            **data
        }

        await self.client.async_emit_event(
            topic_name=f"{domain}-events",
            event_type=f"{domain}.{event_type}",
            subject=f"{domain}s/{entity_id}",
            data=enriched_data
        )

    async def publish_integration_event(self, event_type: str, data: dict,
                                      target_service: str = None,
                                      correlation_id: str = None):
        """Publish cross-service integration events."""

        integration_data = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "source_service": self.service_name,
            "target_service": target_service,
            "published_at": datetime.utcnow().isoformat(),
            "event_version": "1.0",
            **data
        }

        await self.client.async_emit_event(
            topic_name="integration-events",
            event_type=f"integration.{event_type}",
            subject=f"services/{self.service_name}",
            data=integration_data
        )
```

### Message Queue Client

```python
from aio_azure_clients_toolbox import ManagedAzureServiceBusSender
import json
import asyncio
from datetime import datetime, timedelta
from typing import Callable, Any

class MessageQueueClient(ManagedAzureServiceBusSender):
    """Enhanced Service Bus client with retry and dead letter handling."""

    def __init__(self, namespace_url: str, queue_name: str, credential,
                 max_retries: int = 3, **kwargs):
        super().__init__(namespace_url, queue_name, credential, **kwargs)
        self.max_retries = max_retries
        self.message_handlers = {}

    async def send_message_with_retry(self, message: dict,
                                    delay_seconds: int = 0,
                                    priority: str = "normal") -> bool:
        """Send message with automatic retry on failure."""

        message_envelope = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "priority": priority,
            "retry_count": 0,
            "payload": message
        }

        for attempt in range(self.max_retries + 1):
            try:
                await self.send_message(
                    json.dumps(message_envelope),
                    delay=delay_seconds
                )
                return True

            except Exception as e:
                if attempt == self.max_retries:
                    # Send to dead letter queue or log
                    await self._handle_failed_message(message_envelope, e)
                    return False

                # Exponential backoff
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
                message_envelope["retry_count"] = attempt + 1

        return False

    async def send_scheduled_message(self, message: dict,
                                   scheduled_time: datetime) -> bool:
        """Send message to be processed at specific time."""

        now = datetime.utcnow()
        if scheduled_time <= now:
            return await self.send_message_with_retry(message)

        delay_seconds = int((scheduled_time - now).total_seconds())
        return await self.send_message_with_retry(message, delay_seconds)

    def register_message_handler(self, message_type: str,
                               handler: Callable[[dict], Any]):
        """Register handler for specific message type."""
        self.message_handlers[message_type] = handler

    async def process_messages(self, max_messages: int = 10):
        """Process messages from queue using registered handlers."""
        receiver = self.get_receiver()

        async with receiver:
            messages = await receiver.receive_messages(max_message_count=max_messages)

            for message in messages:
                try:
                    # Parse message envelope
                    envelope = json.loads(str(message))
                    payload = envelope.get("payload", {})
                    message_type = payload.get("type")

                    # Find and execute handler
                    if message_type in self.message_handlers:
                        handler = self.message_handlers[message_type]
                        await handler(payload)

                        # Complete message
                        await receiver.complete_message(message)
                    else:
                        # No handler found, abandon message
                        await receiver.abandon_message(message)

                except json.JSONDecodeError:
                    # Invalid JSON, dead letter the message
                    await receiver.dead_letter_message(
                        message,
                        reason="Invalid JSON",
                        error_description="Message is not valid JSON"
                    )

                except Exception as e:
                    # Handler failed, dead letter after max retries
                    retry_count = envelope.get("retry_count", 0)

                    if retry_count >= self.max_retries:
                        await receiver.dead_letter_message(
                            message,
                            reason="Handler failed",
                            error_description=str(e)
                        )
                    else:
                        # Abandon for retry
                        await receiver.abandon_message(message)

    async def _handle_failed_message(self, message: dict, error: Exception):
        """Handle permanently failed messages."""
        failed_message = {
            "original_message": message,
            "error": str(error),
            "failed_at": datetime.utcnow().isoformat(),
            "service": self.service_bus_queue_name
        }

        # Log the failure (implement your logging strategy)
        logger.error(f"Message failed permanently: {failed_message}")

        # Could send to dead letter queue, write to storage, etc.
```

## Factory Pattern for Client Creation

```python
from abc import ABC, abstractmethod
from typing import TypeVar, Generic

T = TypeVar('T')

class ClientFactory(ABC, Generic[T]):
    """Abstract factory for creating Azure clients."""

    @abstractmethod
    def create_client(self, config: AzureConfig) -> T:
        pass

class CosmosClientFactory(ClientFactory[UserRepository]):
    """Factory for creating Cosmos clients."""

    def create_client(self, config: AzureConfig) -> UserRepository:
        return UserRepository(config)

class BlobClientFactory(ClientFactory[DocumentStorageClient]):
    """Factory for creating Blob storage clients."""

    def create_client(self, config: AzureConfig) -> DocumentStorageClient:
        return DocumentStorageClient(
            storage_url=config.storage_account_url,
            credential=config.get_credential()
        )

class ClientManager:
    """Manages lifecycle of multiple Azure clients."""

    def __init__(self, config: AzureConfig):
        self.config = config
        self.clients = {}
        self.factories = {
            "cosmos": CosmosClientFactory(),
            "blob": BlobClientFactory()
        }

    def get_client(self, client_type: str):
        """Get or create client of specified type."""
        if client_type not in self.clients:
            if client_type not in self.factories:
                raise ValueError(f"Unknown client type: {client_type}")

            factory = self.factories[client_type]
            self.clients[client_type] = factory.create_client(self.config)

        return self.clients[client_type]

    async def close_all(self):
        """Close all managed clients."""
        for client in self.clients.values():
            if hasattr(client, 'close'):
                await client.close()

        self.clients.clear()

# Usage
config = AzureConfig.from_environment()
client_manager = ClientManager(config)

# Get clients as needed
user_repo = client_manager.get_client("cosmos")
doc_storage = client_manager.get_client("blob")

# Use clients
user = await user_repo.create_user({"name": "John", "email": "john@example.com"})
doc_info = await doc_storage.upload_document("user-docs/profile.pdf", pdf_content)

# Cleanup
await client_manager.close_all()
```

## Decorator Patterns for Cross-Cutting Concerns

```python
from functools import wraps
import time
import logging

def with_metrics(operation_name: str):
    """Decorator to add metrics to client operations."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time

                # Record success metrics
                logger.info(f"{operation_name} completed", extra={
                    "operation": operation_name,
                    "duration_ms": duration * 1000,
                    "status": "success"
                })

                return result

            except Exception as e:
                duration = time.time() - start_time

                # Record error metrics
                logger.error(f"{operation_name} failed", extra={
                    "operation": operation_name,
                    "duration_ms": duration * 1000,
                    "status": "error",
                    "error": str(e)
                })

                raise

        return wrapper
    return decorator

class MetricsEnabledUserRepository(UserRepository):
    """User repository with automatic metrics collection."""

    @with_metrics("user_create")
    async def create_user(self, user_data: dict) -> dict:
        return await super().create_user(user_data)

    @with_metrics("user_get")
    async def get_user(self, user_id: str) -> dict | None:
        return await super().get_user(user_id)

    @with_metrics("user_update")
    async def update_user(self, user_id: str, updates: dict, etag: str = None) -> dict:
        return await super().update_user(user_id, updates, etag)
```