# Troubleshooting

Common issues and solutions when using `aio-azure-clients-toolbox`.

## Connection Pool Issues

### ConnectionsExhausted Error

**Symptom**: `ConnectionsExhausted: No connections available`

**Causes**:
- Pool size too small for concurrent load
- Client limit per connection too low
- Connections not being properly released

**Solutions**:

```python
# Increase pool size
client = ManagedCosmos(
    # ... other params
    max_size=20,  # Increase from default 10
    client_limit=200  # Increase from default 100
)

# Check for connection leaks
async with client.get_container_client() as container:
    # Always use context manager
    result = await container.create_item(body=document)
# Connection automatically released here
```

### Connection Timeouts

**Symptom**: Operations timing out or hanging

**Causes**:
- Idle timeout too short
- Network connectivity issues
- Azure service throttling

**Solutions**:

```python
# Increase timeouts
client = ManagedCosmos(
    # ... other params
    max_idle_seconds=600,  # 10 minutes instead of 5
    max_lifespan_seconds=7200  # 2 hours instead of 1
)

# Enable debug logging
import logging
logging.getLogger("aio_azure_clients_toolbox.connection_pooling").setLevel(logging.DEBUG)
```

### Memory Usage Issues

**Symptom**: High memory consumption with pooled clients

**Causes**:
- Too many connections in pool
- Large idle timeouts
- Connection leaks

**Solutions**:

```python
# Optimize for memory usage
client = ManagedCosmos(
    # ... other params
    max_size=5,           # Smaller pool
    max_idle_seconds=60,  # Quick recycling
    client_limit=50       # Fewer clients per connection
)

# Monitor pool health
print(f"Ready connections: {client.pool.ready_connection_count}")
```

## Authentication Issues

### DefaultAzureCredential Failures

**Symptom**: Authentication errors or permission denied

**Causes**:
- Missing environment variables
- Insufficient permissions
- Managed identity not configured

**Solutions**:

```bash
# Set environment variables
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"
export AZURE_TENANT_ID="your-tenant-id"

# Or use Azure CLI
az login
```

**Check permissions**:
- Cosmos DB: "Cosmos DB Account Contributor" or "Cosmos DB Data Contributor"
- Blob Storage: "Storage Blob Data Contributor"
- Service Bus: "Azure Service Bus Data Sender/Receiver"
- Event Hub: "Azure Event Hubs Data Sender"
- Event Grid: "Event Grid Data Sender"

### Token Refresh Issues

**Symptom**: Intermittent authentication failures

**Causes**:
- Long-running processes with expired tokens
- Credential caching issues

**Solutions**:

```python
# Force credential refresh by recreating clients periodically
async def refresh_clients():
    await client.close()
    client = create_new_client_instance()

# Or use shorter connection lifespans
client = ManagedCosmos(
    # ... other params
    max_lifespan_seconds=1800  # 30 minutes
)
```

## Service-Specific Issues

### Cosmos DB

#### Request Rate Too Large (429 errors)

**Symptom**: `CosmosHttpResponseError` with status code 429

**Solutions**:

```python
# Implement retry with exponential backoff
from azure.cosmos import exceptions
import asyncio

async def cosmos_operation_with_retry(container, operation, max_retries=3):
    for attempt in range(max_retries + 1):
        try:
            return await operation(container)
        except exceptions.CosmosHttpResponseError as e:
            if e.status_code == 429 and attempt < max_retries:
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
            else:
                raise

# Reduce connection pool size to limit concurrent requests
cosmos_client = ManagedCosmos(
    # ... other params
    max_size=3,
    client_limit=25
)
```

#### Partition Key Issues

**Symptom**: Cross-partition queries failing or slow

**Solutions**:

```python
# Always specify partition key when possible
async with cosmos_client.get_container_client() as container:
    # Good: Uses partition key
    item = await container.read_item(
        item="item-id",
        partition_key="partition-value"
    )

    # Avoid: Cross-partition query
    items = list(container.query_items(
        query="SELECT * FROM c WHERE c.id = @id",
        parameters=[{"name": "@id", "value": "item-id"}],
        enable_cross_partition_query=True  # Required but inefficient
    ))
```

### Blob Storage

#### Large File Upload Issues

**Symptom**: Timeouts or memory errors with large files

**Solutions**:

```python
# Stream large files instead of loading into memory
import aiofiles

async def upload_large_file(blob_client, file_path: str):
    async with aiofiles.open(file_path, 'rb') as file:
        # Upload in chunks
        chunk_size = 4 * 1024 * 1024  # 4MB chunks

        async with blob_client.get_blob_client("large-file.bin") as client:
            await client.upload_blob(
                file,
                overwrite=True,
                max_single_put_size=chunk_size,
                max_block_size=chunk_size
            )
```

#### SAS Token Issues

**Symptom**: Access denied when using SAS URLs

**Solutions**:

```python
# Check SAS token permissions and expiry
from azure.storage.blob import BlobSasPermissions
from datetime import datetime, timedelta

# Ensure proper permissions
permissions = BlobSasPermissions(read=True, write=True)

# Check token hasn't expired
sas_token = await blob_client.get_blob_sas_token(
    "file.txt",
    permission=permissions,
    expiry_hours=24  # Ensure sufficient time
)

# Verify the URL works
sas_url = await blob_client.get_blob_sas_url("file.txt", permission=permissions)
print(f"SAS URL: {sas_url}")
```

### Service Bus

#### Connection String vs Managed Identity

**Symptom**: Authentication issues with Service Bus

**Note**: This library uses `DefaultAzureCredential`, not connection strings.

```python
# Correct: Using managed identity
service_bus = ManagedAzureServiceBusSender(
    service_bus_namespace_url="https://namespace.servicebus.windows.net",
    service_bus_queue_name="queue-name",
    credential=DefaultAzureCredential()
)

# For connection strings, use Azure SDK directly:
# from azure.servicebus.aio import ServiceBusClient
# client = ServiceBusClient.from_connection_string(connection_string)
```

## Performance Issues

### High Latency

**Symptoms**: Slow response times

**Diagnosis**:

```python
import time
import logging

# Enable performance logging
logging.getLogger("aio_azure_clients_toolbox.connection_pooling").setLevel(logging.DEBUG)

# Measure operation times
async def timed_operation(operation):
    start = time.time()
    try:
        result = await operation()
        duration = time.time() - start
        print(f"Operation completed in {duration:.3f}s")
        return result
    except Exception as e:
        duration = time.time() - start
        print(f"Operation failed after {duration:.3f}s: {e}")
        raise

# Check pool utilization
def check_pool_health(client):
    pool = client.pool
    print(f"Ready connections: {pool.ready_connection_count}")
    for i, conn in enumerate(pool._pool):
        print(f"Connection {i}: clients={conn.current_client_count}, ready={conn.is_ready}")
```

**Solutions**:

```python
# Optimize pool configuration
client = ManagedCosmos(
    # ... other params
    client_limit=50,      # Reduce contention
    max_size=15,          # More connections
    max_idle_seconds=300, # Keep connections warm
)

# Pre-warm connections
async def warm_up_pool(client, operations=10):
    """Pre-warm connection pool."""
    async def dummy_operation():
        async with client.get_container_client() as container:
            # Lightweight operation to establish connection
            pass

    await asyncio.gather(*[dummy_operation() for _ in range(operations)])
```

## Debugging

### Enable Debug Logging

```python
import logging

# Configure detailed logging
logging.basicConfig(level=logging.DEBUG)

# Specific loggers
loggers = [
    "aio_azure_clients_toolbox.connection_pooling",
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.servicebus",
    "azure.eventhub",
    "azure.cosmos"
]

for logger_name in loggers:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
```

### Network Connectivity

```python
import aiohttp
import asyncio

async def test_connectivity(endpoint: str):
    """Test network connectivity to Azure endpoint."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://{endpoint}") as response:
                print(f"Connectivity to {endpoint}: {response.status}")
                return response.status < 400
    except Exception as e:
        print(f"Connectivity test failed for {endpoint}: {e}")
        return False

# Test Azure service endpoints
endpoints = [
    "your-cosmos.documents.azure.com",
    "yourstorage.blob.core.windows.net",
    "your-namespace.servicebus.windows.net"
]

for endpoint in endpoints:
    result = await test_connectivity(endpoint)
    print(f"{endpoint}: {'✓' if result else '✗'}")
```

### Configuration Validation

```python
def validate_azure_config():
    """Validate Azure configuration."""
    import os

    required_vars = [
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_TENANT_ID"
    ]

    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print(f"Missing environment variables: {missing}")
        return False

    print("Azure configuration appears valid")
    return True

# Run validation
validate_azure_config()
```
