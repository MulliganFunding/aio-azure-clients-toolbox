# Cosmos DB Client

Azure Cosmos DB client implementations with connection pooling and lifecycle management.

## Available Classes

| Class | Type | Description |
|-------|------|-------------|
| `Cosmos` | Basic | Direct wrapper with connection management |
| `ManagedCosmos` | Managed | Connection pooling implementation |
| `SimpleCosmos` | Basic | Minimal implementation for simple use cases |

## ManagedCosmos

Recommended client with built-in connection pooling.

### Constructor

```python
ManagedCosmos(
    endpoint: str,
    dbname: str,
    container_name: str,
    credential_factory: CredentialFactory,
    client_limit: int = 100,
    max_size: int = 10,
    max_idle_seconds: int = 30,
    max_lifespan_seconds: int = 60,
    pool_connection_create_timeout: int = 10,
    pool_get_timeout: int = 60
)
```

### Parameters

- **endpoint**: Cosmos DB account endpoint URL
- **dbname**: Target database name
- **container_name**: Target container name
- **credential_factory**: Factory function that returns Azure authentication credentials
- **client_limit**: Maximum clients per pooled connection (default: 100)
- **max_size**: Connection pool size (default: 10)
- **max_idle_seconds**: Connection idle timeout (default: 30)
- **max_lifespan_seconds**: Maximum connection lifetime (default: 60)
- **pool_connection_create_timeout**: Timeout for creating connections in the pool (default: 10 seconds)
- **pool_get_timeout**: Timeout for acquiring connections from the pool (default: 60 seconds)

### Usage Example

```python
from azure.identity.aio import DefaultAzureCredential
from aio_azure_clients_toolbox import ManagedCosmos

# Initialize client
cosmos = ManagedCosmos(
    endpoint="https://your-account.documents.azure.com:443/",
    dbname="your-database",
    container_name="your-container",
    credential_factory=lambda: DefaultAzureCredential()
)

# Document operations
async with cosmos.get_container_client() as container:
    # Create document
    document = {"id": "1", "name": "example", "category": "test"}
    result = await container.create_item(body=document)

    # Read document
    item = await container.read_item(item="1", partition_key="test")

    # Update document
    item["modified"] = True
    updated = await container.replace_item(item="1", body=item)

    # Delete document
    await container.delete_item(item="1", partition_key="test")
```

### Query Operations

```python
async with cosmos.get_container_client() as container:
    # SQL query
    query = "SELECT * FROM c WHERE c.category = @category"
    parameters = [{"name": "@category", "value": "test"}]

    items = []
    async for item in container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True
    ):
        items.append(item)
```

### Error Handling

```python
from azure.cosmos import exceptions

async with cosmos.get_container_client() as container:
    try:
        item = await container.read_item(item="nonexistent", partition_key="test")
    except exceptions.CosmosResourceNotFoundError:
        print("Document not found")
    except exceptions.CosmosHttpResponseError as e:
        print(f"HTTP error: {e.status_code}")
```

## Cosmos (Basic Client)

Non-pooled client with connection lifecycle management.

### Constructor

```python
Cosmos(
    endpoint: str,
    dbname: str,
    container_name: str,
    credential: DefaultAzureCredential,
    cosmos_client_ttl_seconds: int = 60
)
```

### Usage Example

```python
from aio_azure_clients_toolbox.clients.cosmos import Cosmos

cosmos = Cosmos(
    endpoint="https://your-account.documents.azure.com:443/",
    dbname="your-database",
    container_name="your-container",
    credential=DefaultAzureCredential()
)

# Connection is managed but not pooled
async with cosmos.get_container_client() as container:
    result = await container.create_item(body=document)

# Close when done
await cosmos.close()
```

## SimpleCosmos

Minimal client for basic operations without connection management.

### Constructor

```python
SimpleCosmos(
    endpoint: str,
    dbname: str,
    container_name: str,
    credential: DefaultAzureCredential
)
```

### Usage Example

```python
from aio_azure_clients_toolbox.clients.cosmos import SimpleCosmos

cosmos = SimpleCosmos(
    endpoint="https://your-account.documents.azure.com:443/",
    dbname="your-database",
    container_name="your-container",
    credential=DefaultAzureCredential()
)

# Get container client
container = await cosmos.get_container_client()

# Direct operations
result = await container.create_item(body=document)

# Manual cleanup required
await cosmos.close()
```

## Subclassing Patterns

### Application-Specific Client

```python
from aio_azure_clients_toolbox import ManagedCosmos
from azure.core import MatchConditions

class DocumentStore(ManagedCosmos):
    def __init__(self, config):
        super().__init__(
            endpoint=config.cosmos_endpoint,
            dbname=config.cosmos_database,
            container_name="documents",
            credential=config.azure_credential()
        )

    async def create_document(self, doc_id: str, content: dict):
        """Create a new document with validation."""
        document = {
            "id": doc_id,
            "content": content,
            "created_at": "2023-01-01T00:00:00Z"
        }

        async with self.get_container_client() as container:
            return await container.create_item(body=document)

    async def update_document(self, doc_id: str, updates: dict):
        """Update document with optimistic concurrency."""
        async with self.get_container_client() as container:
            # Read current document
            current = await container.read_item(
                item=doc_id,
                partition_key=doc_id
            )

            # Apply updates
            current.update(updates)

            # Replace with etag check
            return await container.replace_item(
                item=doc_id,
                body=current,
                match_condition=MatchConditions.IfNotModified,
                etag=current["_etag"]
            )
```

### Repository Pattern

```python
class UserRepository(ManagedCosmos):
    container_name = "users"

    async def get_user(self, user_id: str):
        async with self.get_container_client() as container:
            try:
                return await container.read_item(
                    item=user_id,
                    partition_key=user_id
                )
            except exceptions.CosmosResourceNotFoundError:
                return None

    async def save_user(self, user: dict):
        async with self.get_container_client() as container:
            return await container.upsert_item(body=user)

    async def find_users_by_email(self, email: str):
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
```

## Performance Optimization

### Batch Operations

```python
async with cosmos.get_container_client() as container:
    # Batch multiple operations
    batch_operations = [
        ("create", {"id": "1", "data": "first"}),
        ("create", {"id": "2", "data": "second"}),
        ("create", {"id": "3", "data": "third"})
    ]

    # Process in parallel (be mindful of rate limits)
    import asyncio

    async def process_item(operation, document):
        if operation == "create":
            return await container.create_item(body=document)

    results = await asyncio.gather(*[
        process_item(op, doc) for op, doc in batch_operations
    ])
```

### Connection Reuse

```python
# Good: Reuse connection for multiple operations
async with cosmos.get_container_client() as container:
    for doc_id in document_ids:
        item = await container.read_item(item=doc_id, partition_key=doc_id)
        # process item

# Avoid: Creating new connections for each operation
# This defeats the purpose of connection pooling
for doc_id in document_ids:
    async with cosmos.get_container_client() as container:
        item = await container.read_item(item=doc_id, partition_key=doc_id)
```

## Configuration Examples

### High-Throughput Application

```python
cosmos = ManagedCosmos(
    endpoint=endpoint,
    dbname=database,
    container_name=container,
    credential=credential,
    client_limit=200,       # Higher client limit
    max_size=20,            # Larger pool
    max_idle_seconds=60,    # Longer idle timeout
    max_lifespan_seconds=300  # 5-minute lifespan
)
```

### Low-Latency Application

```python
cosmos = ManagedCosmos(
    endpoint=endpoint,
    dbname=database,
    container_name=container,
    credential=credential,
    client_limit=50,        # Conservative limit
    max_size=5,             # Smaller pool
    max_idle_seconds=10,    # Quick recycling
    max_lifespan_seconds=60   # Short lifespan
)
```