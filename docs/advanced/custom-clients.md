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
```
