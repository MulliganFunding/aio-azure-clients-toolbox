# Event Hub Client

Azure Event Hub clients for event streaming with connection pooling support.

## Available Classes

| Class | Type | Description |
|-------|------|-------------|
| `Eventhub` | Basic | Direct Event Hub operations |
| `ManagedAzureEventhubProducer` | Managed | Connection pooling for producers |

## ManagedAzureEventhubProducer

Recommended client with connection pooling for high-throughput event streaming.

### Constructor

```python
ManagedAzureEventhubProducer(
    eventhub_namespace: str,
    eventhub_name: str,
    credential: DefaultAzureCredential,
    eventhub_transport_type: str = TRANSPORT_PURE_AMQP,
    client_limit: int = 100,
    max_size: int = 10,
    max_idle_seconds: int = 300,
    max_lifespan_seconds: int = None,
    ready_message: str = None
)
```

### Parameters

- **eventhub_namespace**: Event Hub namespace (without .servicebus.windows.net)
- **eventhub_name**: Target Event Hub name
- **credential**: Azure authentication credential
- **eventhub_transport_type**: Transport protocol (default: AMQP)
- **client_limit**: Maximum clients per pooled connection
- **max_size**: Connection pool size
- **max_idle_seconds**: Connection idle timeout
- **max_lifespan_seconds**: Maximum connection lifetime
- **ready_message**: Message sent to validate connection readiness

### Methods

#### send_event

```python
async def send_event(
    data: str | bytes | dict,
    partition_key: str = None,
    partition_id: str = None
) -> None
```

Send event to Event Hub.

## Usage Examples

### Basic Event Sending

```python
from azure.identity.aio import DefaultAzureCredential
from aio_azure_clients_toolbox.clients.eventhub import ManagedAzureEventhubProducer
import json

# Initialize producer
producer = ManagedAzureEventhubProducer(
    eventhub_namespace="your-namespace",
    eventhub_name="your-eventhub",
    credential=DefaultAzureCredential(),
    ready_message='{"eventType": "connection-established"}'
)

# Send simple event
await producer.send_event("Simple event message")

# Send JSON event
event_data = {
    "event_type": "user_action",
    "user_id": 12345,
    "action": "login",
    "timestamp": "2023-01-01T12:00:00Z"
}
await producer.send_event(json.dumps(event_data))

# Send with partition key for ordering
await producer.send_event(
    json.dumps(event_data),
    partition_key="user-12345"
)
```

### Batch Event Processing

```python
async def send_batch_events(producer, events: list):
    """Send multiple events efficiently."""

    import asyncio

    # Send events concurrently (be mindful of rate limits)
    await asyncio.gather(*[
        producer.send_event(json.dumps(event)) for event in events
    ])

# Usage
events = [
    {"id": 1, "type": "order", "amount": 100},
    {"id": 2, "type": "order", "amount": 250},
    {"id": 3, "type": "order", "amount": 75}
]

await send_batch_events(producer, events)
```

### Partitioned Events

```python
# Send events to specific partition for ordering
user_events = [
    {"user_id": "user-1", "action": "login"},
    {"user_id": "user-1", "action": "view_product"},
    {"user_id": "user-1", "action": "purchase"}
]

for event in user_events:
    await producer.send_event(
        json.dumps(event),
        partition_key=event["user_id"]  # Ensures ordering per user
    )
```

## Eventhub (Basic Client)

Non-pooled client for simpler use cases.

### Constructor

```python
Eventhub(
    eventhub_namespace: str,
    eventhub_name: str,
    credential: DefaultAzureCredential,
    eventhub_transport_type: str = TRANSPORT_PURE_AMQP
)
```

### Usage Example

```python
from aio_azure_clients_toolbox.clients.eventhub import Eventhub

# Create basic client
eventhub = Eventhub(
    eventhub_namespace="your-namespace",
    eventhub_name="your-eventhub",
    credential=DefaultAzureCredential()
)

# Get producer client
producer = eventhub.get_client()

# Send event
from azure.eventhub import EventData
event = EventData(json.dumps({"message": "Hello Event Hub"}))

async with producer:
    await producer.send_batch([event])
```

## Application Patterns

### Event Streaming Pipeline

```python
class EventStream:
    def __init__(self, producer):
        self.producer = producer
        self.event_queue = asyncio.Queue()

    async def emit_event(self, event_type: str, data: dict):
        """Add event to processing queue."""
        event = {
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "application"
        }
        await self.event_queue.put(event)

    async def process_events(self):
        """Background task to send events from queue."""
        while True:
            try:
                event = await self.event_queue.get()
                await self.producer.send_event(
                    json.dumps(event),
                    partition_key=event.get("user_id", "default")
                )
                self.event_queue.task_done()
            except Exception as e:
                logger.error(f"Failed to send event: {e}")
```

### Event Aggregation

```python
class EventAggregator:
    def __init__(self, producer, batch_size: int = 100, flush_interval: int = 30):
        self.producer = producer
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.events = []
        self.last_flush = time.time()

    async def add_event(self, event: dict):
        """Add event to batch."""
        self.events.append(event)

        # Flush if batch is full or interval exceeded
        if (len(self.events) >= self.batch_size or
            time.time() - self.last_flush > self.flush_interval):
            await self.flush()

    async def flush(self):
        """Send accumulated events."""
        if not self.events:
            return

        # Send events in parallel
        await asyncio.gather(*[
            self.producer.send_event(json.dumps(event))
            for event in self.events
        ])

        self.events.clear()
        self.last_flush = time.time()
```

### Error Handling and Retry

```python
class ResilientEventProducer:
    def __init__(self, producer, max_retries: int = 3):
        self.producer = producer
        self.max_retries = max_retries

    async def send_event_with_retry(self, event_data: dict):
        """Send event with exponential backoff retry."""

        for attempt in range(self.max_retries + 1):
            try:
                await self.producer.send_event(json.dumps(event_data))
                return  # Success

            except Exception as e:
                if attempt == self.max_retries:
                    # Final attempt failed, log and potentially send to DLQ
                    logger.error(f"Failed to send event after {self.max_retries} retries: {e}")
                    await self._handle_failed_event(event_data, e)
                    raise

                # Exponential backoff
                wait_time = 2 ** attempt
                logger.warning(f"Event send failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)

    async def _handle_failed_event(self, event_data: dict, error: Exception):
        """Handle permanently failed events."""
        # Could send to dead letter queue, write to file, etc.
        failed_event = {
            "original_event": event_data,
            "error": str(error),
            "failed_at": datetime.utcnow().isoformat()
        }
        # Implementation depends on your error handling strategy
```

## Configuration

### Event Hub Setup

Ensure your Event Hub has:

- Namespace created with appropriate pricing tier
- Event Hub created with sufficient partition count
- RBAC permissions: "Azure Event Hubs Data Sender"
- Consumer groups configured for downstream processing

### Performance Tuning

```python
# High-throughput configuration
producer = ManagedAzureEventhubProducer(
    eventhub_namespace=namespace,
    eventhub_name=hub_name,
    credential=credential,
    client_limit=200,        # Higher concurrency
    max_size=20,             # Larger pool
    max_idle_seconds=120,    # Longer idle timeout
    ready_message='{"type": "health_check"}'
)
```

### Transport Types

```python
from azure.eventhub import TransportType

# Available transport types
TRANSPORT_PURE_AMQP = TransportType.Amqp      # Default, most efficient
TRANSPORT_AMQP_OVER_WEBSOCKET = TransportType.AmqpOverWebsocket  # For restrictive networks
```

## Monitoring

### Connection Health

```python
# Check pool status
print(f"Ready connections: {producer.pool.ready_connection_count}")

# Enable detailed logging
import logging
logging.getLogger("azure.eventhub").setLevel(logging.DEBUG)
logging.getLogger("aio_azure_clients_toolbox.connection_pooling").setLevel(logging.DEBUG)
```

### Event Metrics

```python
class MetricsEventProducer:
    def __init__(self, producer):
        self.producer = producer
        self.sent_count = 0
        self.error_count = 0
        self.last_reset = time.time()

    async def send_event(self, data):
        try:
            await self.producer.send_event(data)
            self.sent_count += 1
        except Exception as e:
            self.error_count += 1
            raise

    def get_metrics(self):
        elapsed = time.time() - self.last_reset
        return {
            "events_sent": self.sent_count,
            "errors": self.error_count,
            "events_per_second": self.sent_count / elapsed if elapsed > 0 else 0
        }
```

## Best Practices

### Event Design

- Include event schema version for compatibility
- Use consistent timestamp formats (ISO 8601)
- Include correlation IDs for distributed tracing
- Keep event size under 1MB (Event Hub limit)

### Partitioning Strategy

- Use partition keys for events that must be ordered
- Distribute load evenly across partitions
- Consider downstream consumer parallelism

### Error Handling

- Implement retry logic with exponential backoff
- Use dead letter queues for permanent failures
- Monitor and alert on error rates
- Log sufficient context for debugging