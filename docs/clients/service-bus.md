# Service Bus Client

Azure Service Bus clients for message queuing with connection pooling support.

## Available Classes

| Class | Type | Description |
|-------|------|-------------|
| `AzureServiceBus` | Basic | Direct Service Bus operations |
| `ManagedAzureServiceBusSender` | Managed | Connection pooling for sending |

## ManagedAzureServiceBusSender

Recommended client with connection pooling for high-throughput sending.

### Constructor

```python
ManagedAzureServiceBusSender(
    service_bus_namespace_url: str,
    service_bus_queue_name: str,
    credential_factory: CredentialFactory,
    client_limit: int = 100,
    max_size: int = 10,
    max_idle_seconds: int = 300,
    max_lifespan_seconds: int = None,
    pool_connection_create_timeout: int = 10,
    pool_get_timeout: int = 60
)
```

### Parameters

- **service_bus_namespace_url**: Service Bus namespace URL
- **service_bus_queue_name**: Target queue name
- **credential_factory**: Factory function that returns Azure authentication credentials
- **client_limit**: Maximum clients per pooled connection
- **max_size**: Connection pool size
- **max_idle_seconds**: Connection idle timeout
- **max_lifespan_seconds**: Maximum connection lifetime
- **pool_connection_create_timeout**: Timeout for creating connections in the pool (default: 10 seconds)
- **pool_get_timeout**: Timeout for acquiring connections from the pool (default: 60 seconds)

### Methods

#### send_message

```python
async def send_message(
    message: str,
    delay: int = 0,
    **kwargs
) -> None
```

Send message to queue with optional delay.

#### get_receiver

```python
def get_receiver() -> ServiceBusReceiver
```

Create receiver for processing messages.

## Usage Examples

### Basic Message Sending

```python
from azure.identity.aio import DefaultAzureCredential
from aio_azure_clients_toolbox import ManagedAzureServiceBusSender

# Initialize sender
sender = ManagedAzureServiceBusSender(
    service_bus_namespace_url="https://your-namespace.servicebus.windows.net",
    service_bus_queue_name="your-queue",
    credential_factory=lambda: DefaultAzureCredential()
)

# Send simple message
await sender.send_message("Hello, Service Bus!")

# Send JSON message
import json
data = {"event_type": "user_created", "user_id": 123}
await sender.send_message(json.dumps(data))

# Send with delay
await sender.send_message("Delayed message", delay=300)  # 5 minutes
```

### Message Processing

```python
# Create receiver for processing
receiver = sender.get_receiver()

async def process_messages():
    async with receiver:
        async for message in receiver:
            try:
                # Process message content
                content = str(message)
                print(f"Received: {content}")

                # Complete message to remove from queue
                await receiver.complete_message(message)

            except Exception as e:
                print(f"Error processing message: {e}")
                # Abandon message to retry later
                await receiver.abandon_message(message)

# Run message processor
await process_messages()
```

### Error Handling and Dead Letter

```python
async def handle_messages_with_dlq():
    async with receiver:
        async for message in receiver:
            try:
                # Attempt to process
                result = await process_business_logic(message)
                await receiver.complete_message(message)

            except BusinessLogicError as e:
                # Send to dead letter queue for manual review
                await receiver.dead_letter_message(
                    message,
                    reason="Business logic failure",
                    error_description=str(e)
                )

            except TransientError:
                # Abandon for retry
                await receiver.abandon_message(message)

            except Exception as e:
                # Log and dead letter for unknown errors
                logger.error(f"Unexpected error: {e}")
                await receiver.dead_letter_message(
                    message,
                    reason="Unexpected error",
                    error_description=str(e)
                )
```

## AzureServiceBus (Basic Client)

Non-pooled client for simpler use cases.

### Constructor

```python
AzureServiceBus(
    service_bus_namespace_url: str,
    service_bus_queue_name: str,
    credential: DefaultAzureCredential
)
```

### Usage Example

```python
from aio_azure_clients_toolbox.clients.service_bus import AzureServiceBus

sbus = AzureServiceBus(
    service_bus_namespace_url="https://your-namespace.servicebus.windows.net",
    service_bus_queue_name="your-queue",
    credential=DefaultAzureCredential()
)

# Send message
await sbus.send_message("Hello from basic client")

# Get receiver
receiver = sbus.get_receiver()

# Close when done
await sbus.close()
```

## Application Patterns

### Producer-Consumer Pattern

```python
class EventProducer:
    def __init__(self, service_bus_client):
        self.sbus = service_bus_client

    async def publish_event(self, event_type: str, data: dict):
        message = {
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.sbus.send_message(json.dumps(message))

class EventConsumer:
    def __init__(self, service_bus_client):
        self.sbus = service_bus_client
        self.handlers = {}

    def register_handler(self, event_type: str, handler):
        self.handlers[event_type] = handler

    async def start_consuming(self):
        receiver = self.sbus.get_receiver()
        async with receiver:
            async for message in receiver:
                try:
                    event = json.loads(str(message))
                    event_type = event.get("event_type")

                    if event_type in self.handlers:
                        await self.handlers[event_type](event["data"])
                        await receiver.complete_message(message)
                    else:
                        await receiver.abandon_message(message)

                except Exception as e:
                    logger.error(f"Message processing failed: {e}")
                    await receiver.dead_letter_message(message)
```

### Request-Response Pattern

```python
class ServiceBusRPC:
    def __init__(self, sender, reply_queue_name):
        self.sender = sender
        self.reply_queue = reply_queue_name
        self.pending_requests = {}

    async def call(self, method: str, params: dict, timeout: int = 30):
        correlation_id = str(uuid.uuid4())

        request = {
            "method": method,
            "params": params,
            "correlation_id": correlation_id,
            "reply_to": self.reply_queue
        }

        # Send request
        await self.sender.send_message(json.dumps(request))

        # Wait for response (simplified - use proper async patterns)
        # Implementation would use asyncio.Event or similar
        return await self._wait_for_response(correlation_id, timeout)
```

### Batch Processing

```python
async def batch_send_messages(sender, messages: list[str], batch_size: int = 10):
    """Send messages in batches to improve throughput."""

    for i in range(0, len(messages), batch_size):
        batch = messages[i:i + batch_size]

        # Send batch concurrently
        await asyncio.gather(*[
            sender.send_message(msg) for msg in batch
        ])

        # Optional: add delay between batches to respect rate limits
        await asyncio.sleep(0.1)
```

## Configuration

### Service Bus Setup

Ensure your Service Bus namespace has:

- Queue created with appropriate settings
- RBAC permissions: "Azure Service Bus Data Sender" and "Data Receiver"
- Dead letter queue enabled for error handling

### Performance Tuning

```python
# High-throughput configuration
sender = ManagedAzureServiceBusSender(
    service_bus_namespace_url=namespace_url,
    service_bus_queue_name=queue_name,
    credential=credential,
    client_limit=200,      # Higher concurrency
    max_size=20,           # Larger pool
    max_idle_seconds=120   # Longer idle timeout
)
```

### Message Properties

```python
from azure.servicebus import ServiceBusMessage

# Create message with properties
message = ServiceBusMessage(
    json.dumps(data),
    content_type="application/json",
    correlation_id="unique-id",
    message_id="msg-123",
    time_to_live=timedelta(hours=1)
)

# Send with properties
async with sender.pool.get() as connection:
    await connection.send_messages(message)
```

## Monitoring and Troubleshooting

### Message Metrics

```python
# Monitor queue depth and processing rates
from azure.servicebus.management.aio import ServiceBusAdministrationClient

admin_client = ServiceBusAdministrationClient(
    fully_qualified_namespace=namespace_url,
    credential=credential
)

queue_info = await admin_client.get_queue_runtime_properties(queue_name)
print(f"Active messages: {queue_info.active_message_count}")
print(f"Dead letter messages: {queue_info.dead_letter_message_count}")
```

### Connection Health

```python
# Check pool health
print(f"Ready connections: {sender.pool.ready_connection_count}")

# Enable debug logging
import logging
logging.getLogger("azure.servicebus").setLevel(logging.DEBUG)
```