# Event Grid Client

Azure Event Grid client for publishing events to multiple topics with async/sync support.

## EventGridClient

Unified client that supports publishing to multiple Event Grid topics.

### Constructor

```python
EventGridClient(
    config: EventGridConfig,
    async_credential: DefaultAzureCredential = None,
    sync_credential: DefaultAzureCredential = None
)
```

### Parameters

- **config**: Event Grid configuration with topic definitions
- **async_credential**: Async Azure credential (for async operations)
- **sync_credential**: Sync Azure credential (for sync operations)

### Configuration Classes

#### EventGridConfig

```python
EventGridConfig(topics: list[EventGridTopicConfig])
```

Container for multiple topic configurations.

#### EventGridTopicConfig

```python
EventGridTopicConfig(
    name: str,
    endpoint: str
)
```

Configuration for individual Event Grid topics.

## Usage Examples

### Basic Setup

```python
from azure.identity.aio import DefaultAzureCredential
from aio_azure_clients_toolbox.clients.eventgrid import (
    EventGridClient,
    EventGridConfig,
    EventGridTopicConfig
)

# Configure topics
config = EventGridConfig([
    EventGridTopicConfig(
        name="user-events",
        endpoint="https://user-events.azure.net/api/events"
    ),
    EventGridTopicConfig(
        name="order-events",
        endpoint="https://order-events.azure.net/api/events"
    )
])

# Create client
client = EventGridClient(
    config=config,
    async_credential=DefaultAzureCredential()
)
```

### Async Event Publishing

```python
# Publish single event
await client.async_emit_event(
    topic_name="user-events",
    event_type="user.created",
    subject="users/12345",
    data={
        "user_id": 12345,
        "email": "user@example.com",
        "created_at": "2023-01-01T12:00:00Z"
    }
)

# Publish with custom event properties
await client.async_emit_event(
    topic_name="order-events",
    event_type="order.completed",
    subject="orders/67890",
    data={
        "order_id": 67890,
        "customer_id": 12345,
        "total_amount": 99.99
    },
    data_version="1.0",
    event_time="2023-01-01T13:00:00Z"
)
```

### Sync Event Publishing

```python
from azure.identity import DefaultAzureCredential as SyncCredential

# Configure for sync operations
client = EventGridClient(
    config=config,
    sync_credential=SyncCredential()
)

# Sync event publishing
client.sync_emit_event(
    topic_name="user-events",
    event_type="user.login",
    subject="users/12345",
    data={"user_id": 12345, "login_time": "2023-01-01T14:00:00Z"}
)
```

### Batch Event Publishing

```python
# Prepare multiple events
events = [
    {
        "topic": "user-events",
        "event_type": "user.updated",
        "subject": "users/1",
        "data": {"user_id": 1, "field": "email"}
    },
    {
        "topic": "user-events",
        "event_type": "user.updated",
        "subject": "users/2",
        "data": {"user_id": 2, "field": "name"}
    }
]

# Send events concurrently
import asyncio

await asyncio.gather(*[
    client.async_emit_event(
        topic_name=event["topic"],
        event_type=event["event_type"],
        subject=event["subject"],
        data=event["data"]
    )
    for event in events
])
```

## Application Patterns

### Event Publisher Service

```python
class EventPublisher:
    def __init__(self, eventgrid_client):
        self.client = eventgrid_client

    async def publish_user_event(self, event_type: str, user_id: int, data: dict):
        """Publish user-related events."""
        await self.client.async_emit_event(
            topic_name="user-events",
            event_type=f"user.{event_type}",
            subject=f"users/{user_id}",
            data={
                "user_id": user_id,
                "timestamp": datetime.utcnow().isoformat(),
                **data
            }
        )

    async def publish_order_event(self, event_type: str, order_id: int, data: dict):
        """Publish order-related events."""
        await self.client.async_emit_event(
            topic_name="order-events",
            event_type=f"order.{event_type}",
            subject=f"orders/{order_id}",
            data={
                "order_id": order_id,
                "timestamp": datetime.utcnow().isoformat(),
                **data
            }
        )

# Usage
publisher = EventPublisher(client)

# Publish user events
await publisher.publish_user_event("created", 123, {"email": "user@example.com"})
await publisher.publish_user_event("login", 123, {"ip_address": "192.168.1.1"})

# Publish order events
await publisher.publish_order_event("created", 456, {"total": 99.99})
await publisher.publish_order_event("shipped", 456, {"tracking_number": "ABC123"})
```

### Domain Event Publishing

```python
class DomainEventPublisher:
    def __init__(self, eventgrid_client):
        self.client = eventgrid_client
        self.event_mappings = {
            "User": "user-events",
            "Order": "order-events",
            "Product": "product-events"
        }

    async def publish_domain_event(self, aggregate_type: str, aggregate_id: str,
                                 event_type: str, event_data: dict):
        """Publish domain events with automatic topic routing."""

        topic_name = self.event_mappings.get(aggregate_type)
        if not topic_name:
            raise ValueError(f"No topic configured for aggregate type: {aggregate_type}")

        await self.client.async_emit_event(
            topic_name=topic_name,
            event_type=f"{aggregate_type.lower()}.{event_type}",
            subject=f"{aggregate_type.lower()}s/{aggregate_id}",
            data={
                "aggregate_id": aggregate_id,
                "aggregate_type": aggregate_type,
                "event_version": "1.0",
                "occurred_at": datetime.utcnow().isoformat(),
                **event_data
            }
        )

# Usage
domain_publisher = DomainEventPublisher(client)

# Publish domain events
await domain_publisher.publish_domain_event(
    "User", "123", "registered",
    {"email": "user@example.com", "plan": "premium"}
)

await domain_publisher.publish_domain_event(
    "Order", "456", "completed",
    {"customer_id": "123", "total_amount": 199.99}
)
```

### Event Enrichment

```python
class EnrichedEventPublisher:
    def __init__(self, eventgrid_client):
        self.client = eventgrid_client

    async def publish_enriched_event(self, topic_name: str, event_type: str,
                                   subject: str, data: dict,
                                   correlation_id: str = None):
        """Publish events with automatic enrichment."""

        # Add standard enrichment fields
        enriched_data = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "source_service": "user-service",
            "schema_version": "1.0",
            "published_at": datetime.utcnow().isoformat(),
            **data
        }

        await self.client.async_emit_event(
            topic_name=topic_name,
            event_type=event_type,
            subject=subject,
            data=enriched_data
        )

# Usage with correlation tracking
correlation_id = "request-123"
enriched_publisher = EnrichedEventPublisher(client)

await enriched_publisher.publish_enriched_event(
    "user-events", "user.created", "users/789",
    {"user_id": 789, "email": "new@example.com"},
    correlation_id=correlation_id
)
```

## Error Handling

```python
from azure.core.exceptions import HttpResponseError

class ResilientEventPublisher:
    def __init__(self, eventgrid_client, max_retries: int = 3):
        self.client = eventgrid_client
        self.max_retries = max_retries

    async def publish_with_retry(self, topic_name: str, event_type: str,
                               subject: str, data: dict):
        """Publish event with retry logic."""

        for attempt in range(self.max_retries + 1):
            try:
                await self.client.async_emit_event(
                    topic_name=topic_name,
                    event_type=event_type,
                    subject=subject,
                    data=data
                )
                return  # Success

            except HttpResponseError as e:
                if e.status_code in [400, 401, 403]:  # Don't retry client errors
                    logger.error(f"Client error publishing event: {e}")
                    raise

                if attempt == self.max_retries:
                    logger.error(f"Failed to publish event after {self.max_retries} retries")
                    raise

                wait_time = 2 ** attempt
                logger.warning(f"Event publish failed (attempt {attempt + 1}), retrying in {wait_time}s")
                await asyncio.sleep(wait_time)

            except Exception as e:
                logger.error(f"Unexpected error publishing event: {e}")
                raise
```

## Configuration Management

### Environment-Based Configuration

```python
import os

def create_eventgrid_config() -> EventGridConfig:
    """Create Event Grid config from environment variables."""

    topics = []

    # Load topics from environment
    topic_names = os.getenv("EVENTGRID_TOPICS", "").split(",")

    for topic_name in topic_names:
        if not topic_name.strip():
            continue

        endpoint_key = f"EVENTGRID_{topic_name.upper()}_ENDPOINT"
        endpoint = os.getenv(endpoint_key)

        if endpoint:
            topics.append(EventGridTopicConfig(
                name=topic_name.strip(),
                endpoint=endpoint
            ))

    return EventGridConfig(topics)

# Usage
config = create_eventgrid_config()
client = EventGridClient(config=config, async_credential=DefaultAzureCredential())
```

### Dynamic Topic Registration

```python
class DynamicEventGridClient:
    def __init__(self, async_credential):
        self.credential = async_credential
        self.topics = {}
        self.client = None

    def add_topic(self, name: str, endpoint: str):
        """Add topic configuration at runtime."""
        self.topics[name] = endpoint
        self._refresh_client()

    def _refresh_client(self):
        """Recreate client with updated topic configuration."""
        topic_configs = [
            EventGridTopicConfig(name=name, endpoint=endpoint)
            for name, endpoint in self.topics.items()
        ]

        config = EventGridConfig(topic_configs)
        self.client = EventGridClient(
            config=config,
            async_credential=self.credential
        )

    async def publish_event(self, topic_name: str, event_type: str,
                          subject: str, data: dict):
        """Publish event to dynamically configured topic."""
        if not self.client:
            raise ValueError("No topics configured")

        await self.client.async_emit_event(
            topic_name=topic_name,
            event_type=event_type,
            subject=subject,
            data=data
        )
```

## Monitoring and Observability

```python
class ObservableEventPublisher:
    def __init__(self, eventgrid_client):
        self.client = eventgrid_client
        self.metrics = {
            "events_published": 0,
            "publish_errors": 0,
            "topics_used": set()
        }

    async def publish_event(self, topic_name: str, event_type: str,
                          subject: str, data: dict):
        """Publish event with metrics collection."""
        start_time = time.time()

        try:
            await self.client.async_emit_event(
                topic_name=topic_name,
                event_type=event_type,
                subject=subject,
                data=data
            )

            # Record success metrics
            self.metrics["events_published"] += 1
            self.metrics["topics_used"].add(topic_name)

            duration = time.time() - start_time
            logger.info(f"Event published successfully", extra={
                "topic": topic_name,
                "event_type": event_type,
                "subject": subject,
                "duration_ms": duration * 1000
            })

        except Exception as e:
            self.metrics["publish_errors"] += 1

            logger.error(f"Failed to publish event", extra={
                "topic": topic_name,
                "event_type": event_type,
                "subject": subject,
                "error": str(e)
            })
            raise

    def get_metrics(self):
        """Get current metrics."""
        return {
            **self.metrics,
            "topics_used": list(self.metrics["topics_used"])
        }
```

## Best Practices

### Event Design

- Use consistent event type naming (domain.action format)
- Include event schema version for compatibility
- Keep event data under 64KB (Event Grid limit)
- Use subjects for filtering and routing

### Topic Organization

- Organize topics by domain or service boundary
- Use separate topics for different data classifications
- Consider subscriber requirements when designing topics

### Security

- Use managed identity when possible
- Rotate Event Grid access keys regularly
- Implement event data encryption for sensitive information

### Performance

- Batch events when possible to reduce API calls
- Use async operations for better throughput
- Monitor Event Grid metrics for rate limiting