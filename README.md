# AIO Azure Clients Toolbox


[![Tests](https://github.com/MulliganFunding/aio-azure-clients-toolbox/workflows/Tests/badge.svg)](https://github.com/MulliganFunding/aio-azure-clients-toolbox/actions)
[![PyPI version](https://badge.fury.io/py/aio-azure-clients-toolbox.svg)](https://badge.fury.io/py/aio-azure-clients-toolbox)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Documentation](https://img.shields.io/badge/docs-github--pages-blue.svg)](https://mulliganfunding.github.io/aio-azure-clients-toolbox/)

High-performance async Python library for Azure SDK clients with intelligent connection pooling.

## Features

- **Async apps**: Built for high-concurrency async applications: we have used this in production at Mulligan Funding for a few years.
- **20-100x Performance Improvement**: Connection pooling reduces operation latency for *some services* from 100-900ms to 1-5ms.
- **Intelligent Connection Management**: Automatic lifecycle management with semaphore-based client limiting.
- **Azure SDK Integration**: Wrappers for Cosmos DB, EventHub, Service Bus, Blob Storage, and EventGrid.
- **Testing Utilities**: Includes pytest fixtures for mocking Azure services.

## Useful Docs

- **[📖 Full Docs](https://mulliganfunding.github.io/aio-azure-clients-toolbox/)** - Complete guide with examples and API reference.
- **[Quick Start Guide](https://mulliganfunding.github.io/aio-azure-clients-toolbox/installation/)**
- **[Connection Pooling Deep Dive](https://mulliganfunding.github.io/aio-azure-clients-toolbox/connection-pooling/)** - Technical details with diagrams.

## Installation

```bash
pip install aio-azure-clients-toolbox
```

## Quick Start

```python
from azure.identity.aio import DefaultAzureCredential
from aio_azure_clients_toolbox import ManagedCosmos

# Traditional approach - slow
cosmos_client = CosmosClient(endpoint, credential)
container = cosmos_client.get_database("db").get_container("container")
await container.create_item({"id": "1"})  # 200ms+ including connection setup

# Connection pooled approach - fast
cosmos_client = ManagedCosmos(
    endpoint="https://your-cosmos.documents.azure.com:443/",
    dbname="your-database",
    container_name="your-container",
    credential=DefaultAzureCredential(),

    # Pool configuration
    client_limit=100,      # Concurrent clients per connection
    max_size=10,           # Maximum connections in pool
    max_idle_seconds=300   # Connection idle timeout
)

async with cosmos_client.get_container_client() as container:
    await container.create_item({"id": "1"})  # 2ms after pool warmup
```

## Supported Azure Services

| Service | Managed Client | Features |
|---------|----------------|----------|
| **Cosmos DB** | `ManagedCosmos` | Document operations with connection pooling |
| **Event Hub** | `ManagedAzureEventhubProducer` | Event streaming with persistent connections |
| **Service Bus** | `ManagedAzureServiceBusSender` | Message queuing with connection management |
| **Blob Storage** | `AzureBlobStorageClient` | File operations with SAS token support |
| **Event Grid** | `EventGridClient` | Event publishing to multiple topics |


## Testing Support

Also includes, built-in pytest fixtures for easy testing:

```python
# tests/conftest.py
pytest_plugins = [
    "aio_azure_clients_toolbox.testing_utils.fixtures",
]

# Use in your tests
async def test_cosmos_operations(cosmos_insertable, document):
    container_client, set_return = cosmos_insertable
    set_return("success")
    result = await cosmos_client.insert_doc(document)
    assert result == "success"
```

---

## Full Client Documentation

For detailed examples and advanced usage patterns, see the [complete documentation](https://mulliganfunding.github.io/aio-azure-clients-toolbox/).

### Azure BlobStorage

```python
from aio_azure_clients_toolbox import AzureBlobStorageClient

client = AzureBlobStorageClient(
    az_storage_url="https://account.blob.core.windows.net",
    container_name="my-container",
    az_credential=DefaultAzureCredential()
)

# Upload and download with SAS token support
await client.upload_blob("file.txt", b"content")
data = await client.download_blob("file.txt")
sas_url = await client.get_blob_sas_url("file.txt")
```

### CosmosDB

```python
from aio_azure_clients_toolbox import ManagedCosmos

client = ManagedCosmos(
    endpoint="https://your-account.documents.azure.com:443/",
    dbname="your-database",
    container_name="your-container",
    credential=DefaultAzureCredential()
)
# Document operations
async with cosmos.get_container_client() as container:
    # Create document
    document = {"id": "1", "name": "example", "category": "test"}
    result = await container.create_item(body=document)

    # Read document
    item = await container.read_item(item="1", partition_key="test")
```

### EventGrid

```python
from aio_azure_clients_toolbox.clients.eventgrid import EventGridClient, EventGridConfig

client = EventGridClient(
    config=EventGridConfig([
        EventGridTopicConfig("topic1", "https://topic1.azure.net/api/event"),
        EventGridTopicConfig("topic2", "https://topic2.azure.net/api/event"),
    ]),
    async_credential=DefaultAzureCredential()
)

await client.async_emit_event("topic1", "event-type", "subject", {"data": "value"})
```

### EventHub

```python
from aio_azure_clients_toolbox import ManagedAzureEventhubProducer

client = ManagedAzureEventhubProducer(
    eventhub_namespace="my-namespace.servicebus.windows.net",
    eventhub_name="my-hub",
    credential=DefaultAzureCredential()
)

await client.send_event('{"event": "data"}')
```

### Service Bus

```python
from aio_azure_clients_toolbox import ManagedAzureServiceBusSender

client = ManagedAzureServiceBusSender(
    service_bus_namespace="my-namespace.servicebus.windows.net",
    queue_name="my-queue",
    credential=DefaultAzureCredential()
)

await client.send_message("Hello, Service Bus!")

# Receiving messages
async with client.get_receiver() as receiver:
    async for message in receiver:
        await process_message(message)

