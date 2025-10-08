# Configuration

Advanced configuration options for Azure clients and connection pooling.

## Connection Pool Configuration

### Basic Parameters

```python
from aio_azure_clients_toolbox import ManagedCosmos

client = ManagedCosmos(
    endpoint="https://cosmos.documents.azure.com/",
    dbname="database",
    container_name="container",
    credential_factory=credential_factory,
    # Connection pool settings
    client_limit=100,           # Clients per connection
    max_size=10,                # Pool size
    max_idle_seconds=300,       # 5 minute idle timeout
    max_lifespan_seconds=3600   # 1 hour max lifetime
)
```

### Parameter Guidelines

#### client_limit

Number of concurrent clients that can share a single connection.

- **Default**: 100


#### max_size

Maximum number of connections in the pool.

- **Default**: 10

#### max_idle_seconds

Time before idle connections are recycled.

- **Default**: 300 seconds (5 minutes)


#### max_lifespan_seconds

Maximum connection lifetime before forced recycling.

- **Default**: None (no limit)

## Service-Specific Configuration

### Cosmos DB

```python
# Low-latency configuration
cosmos_client = ManagedCosmos(
    endpoint=endpoint,
    dbname=database,
    container_name=container,
    credential=credential,
    client_limit=50,           # Lower contention
    max_size=5,                # Smaller pool
    max_idle_seconds=60,       # Quick recycling
    max_lifespan_seconds=1800  # 30-minute rotation
)

# High-throughput configuration
cosmos_client = ManagedCosmos(
    endpoint=endpoint,
    dbname=database,
    container_name=container,
    credential=credential,
    client_limit=200,          # Maximum sharing
    max_size=20,               # Large pool
    max_idle_seconds=300,      # Standard timeout
    max_lifespan_seconds=7200  # 2-hour rotation
)
```

### Service Bus

```python
# Message processing optimization
service_bus = ManagedAzureServiceBusSender(
    service_bus_namespace_url=namespace_url,
    service_bus_queue_name=queue_name,
    credential=credential,
    client_limit=100,          # Standard sharing
    max_size=15,               # Medium pool for message bursts
    max_idle_seconds=120,      # Quick idle timeout
    max_lifespan_seconds=3600  # 1-hour rotation
)
```

### Event Hub

```python
# Event streaming optimization
eventhub = ManagedAzureEventhubProducer(
    eventhub_namespace=namespace,
    eventhub_name=hub_name,
    credential=credential,
    client_limit=150,          # Higher sharing for events
    max_size=10,               # Standard pool
    max_idle_seconds=180,      # 3-minute timeout
    max_lifespan_seconds=5400, # 90-minute rotation
    ready_message='{"type": "health_check"}'
)
```
