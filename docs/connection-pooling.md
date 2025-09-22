# Connection Pooling

## Overview

Connection pooling is the core feature that distinguishes this library from using Azure SDK clients directly. The pooling mechanism maintains persistent connections to Azure services, reducing connection overhead and improving application performance.

## Architecture

The connection pooling system consists of three main components:

### AbstractorConnector

Base class that defines the interface for creating and managing connections:

- `create()`: Establishes new connections
- `ready()`: Validates connection readiness
- `close()`: Cleanup and connection termination

### SharedTransportConnection

Manages individual connections within the pool:

- **Connection Sharing**: Multiple clients can use the same connection simultaneously
- **Idle Timeout**: Connections are recycled after configured idle periods
- **Lifespan Management**: Connections are replaced after maximum lifetime
- **Client Limits**: Controls maximum concurrent clients per connection

### ConnectionPool

Coordinates multiple shared connections:

- **Pool Size**: Configurable number of connections maintained
- **Load Balancing**: Distributes clients across available connections
- **Connection Recycling**: Manages connection lifecycle automatically

## Configuration Parameters

### Client Limit (per connection)

```python
client_limit=100  # Default
```

Maximum number of concurrent clients that can share a single connection. Based on Azure SDK recommendations for shared transport connections.

### Pool Size

```python
max_size=10  # Default
```

Maximum number of connections maintained in the pool. Larger pools support higher concurrency but consume more resources.

### Idle Timeout

```python
max_idle_seconds=300  # Default: 5 minutes
```

Time before idle connections are recycled. Prevents Azure from closing connections due to inactivity.

### Connection Lifespan

```python
max_lifespan_seconds=3600  # Optional: 1 hour
```

Maximum time a connection remains active before forced recycling. Helps prevent long-lived connection issues.

## Implementation Details

### Connection Selection

The pool uses a binary heap to efficiently select the most suitable connection:

1. **Fewest Active Clients**: Prioritizes connections with fewer active clients
2. **Longest Idle Time**: Prefers connections that have been idle longer
3. **Connection Readiness**: Only selects connections that have passed readiness checks

### Thread Safety

All connection pool operations are async-safe:

- **Semaphores**: Control client limits per connection
- **Locks**: Prevent race conditions during connection creation/destruction
- **Atomic Operations**: Ensure consistent pool state

### Error Handling

The pool automatically handles connection failures:

- **Timeout Errors**: Connections are marked for recycling
- **Service Errors**: Failed connections are removed from the pool
- **Graceful Degradation**: New connections are created as needed

## Usage Patterns

### Managed Clients

Most clients inherit from `AbstractorConnector` and provide automatic pooling:

```python
from aio_azure_clients_toolbox import ManagedCosmos

client = ManagedCosmos(
    endpoint="https://cosmos.documents.azure.com/",
    dbname="database",
    container_name="container",
    credential=credential,
    client_limit=50,        # Clients per connection
    max_size=5,             # Pool size
    max_idle_seconds=600    # 10 minute timeout
)

# Connection is automatically managed
async with client.get_container_client() as container:
    await container.create_item(body=document)
```

### Direct Pool Usage

For custom implementations, use the pool directly:

```python
from aio_azure_clients_toolbox.connection_pooling import ConnectionPool

pool = ConnectionPool(
    connector=custom_connector,
    client_limit=100,
    max_size=10,
    max_idle_seconds=300
)

async with pool.get() as connection:
    # Use connection for operations
    result = await connection.some_operation()
```

## Performance Considerations

### Connection Overhead

Creating Azure service connections involves:

- TLS handshake
- Authentication token exchange
- Service endpoint resolution

Connection pooling amortizes this overhead across multiple operations.

### Memory Usage

Each pooled connection consumes memory for:

- Socket buffers
- Authentication tokens
- Client state

Monitor memory usage when configuring large pools.

### Concurrency Limits

Azure services impose various limits:

- **Cosmos DB**: 100 concurrent connections per client
- **Service Bus**: Connection limits vary by tier
- **Event Hub**: Partition-based limits

Configure pool parameters within service limits.

## Monitoring

### Connection State

Check pool health using built-in properties:

```python
# Number of ready connections
ready_count = pool.ready_connection_count

# Check individual connection status
for connection in pool._pool:
    print(f"Clients: {connection.current_client_count}")
    print(f"Ready: {connection.is_ready}")
```

### Logging

Enable debug logging to monitor pool behavior:

```python
import logging
logging.getLogger("aio_azure_clients_toolbox.connection_pooling").setLevel(logging.DEBUG)
```

## Troubleshooting

### Connection Exhaustion

If you see `ConnectionsExhausted` errors:

1. Increase `client_limit` parameter
2. Increase `max_size` for larger pools
3. Check for connection leaks in application code

### Idle Timeouts

For frequent Azure timeout errors:

1. Reduce `max_idle_seconds`
2. Implement application-level connection warming
3. Monitor Azure service health

### Performance Issues

For poor performance:

1. Verify connection pooling is enabled (use Managed clients)
2. Check pool configuration matches workload patterns
3. Monitor connection reuse rates