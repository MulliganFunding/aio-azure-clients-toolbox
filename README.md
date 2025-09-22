# AIO Azure Clients Toolbox

[![PyPI version](https://badge.fury.io/py/aio-azure-clients-toolbox.svg)](https://badge.fury.io/py/aio-azure-clients-toolbox)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/badge/docs-github--pages-blue.svg)](https://mulliganfunding.github.io/aio-azure-clients-toolbox/)

High-performance async Python library for Azure SDK clients with intelligent connection pooling.

## 🚀 Key Features

- **20-100x Performance Improvement**: Connection pooling reduces operation latency from 100-900ms to 1-5ms
- **Intelligent Connection Management**: Automatic lifecycle management with semaphore-based client limiting
- **Azure SDK Integration**: Wrappers for Cosmos DB, Event Hub, Service Bus, Blob Storage, and Event Grid
- **Testing Utilities**: Includes pytest fixtures for mocking Azure services
- **Async apps**: Built for high-concurrency async applications: we have used this in production at Mulligan Funding for a few years.

## 📚 Documentation

- **[📖 Full Documentation](https://mulliganfunding.github.io/aio-azure-clients-toolbox/)** - Complete guide with examples and API reference
- **[🔧 Connection Pooling Deep Dive](https://mulliganfunding.github.io/aio-azure-clients-toolbox/connection-pooling/)** - Technical details with diagrams
- **[⚡ Quick Start Guide](https://mulliganfunding.github.io/aio-azure-clients-toolbox/installation/)** - Get up and running in minutes

## 🏆 Performance Comparison

| Metric | Direct Azure SDK | Connection Pooling | Improvement |
|--------|------------------|-------------------|-------------|
| **Connection Time** | 100-500ms per operation | 1-5ms after warmup | **20-100x faster** |
| **Memory Usage** | High (new client per op) | Low (shared connections) | **5-10x reduction** |
| **Concurrency** | Limited by connection overhead | Up to `client_limit × pool_size` | **10-50x higher** |

## 📦 Installation

```bash
pip install aio-azure-clients-toolbox
```

## ⚡ Quick Start

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

## 🎯 Supported Azure Services

| Service | Managed Client | Features |
|---------|----------------|----------|
| **Cosmos DB** | `ManagedCosmos` | Document operations with connection pooling |
| **Event Hub** | `ManagedAzureEventhubProducer` | Event streaming with persistent connections |
| **Service Bus** | `ManagedAzureServiceBusSender` | Message queuing with connection management |
| **Blob Storage** | `AzureBlobStorageClient` | File operations with SAS token support |
| **Event Grid** | `EventGridClient` | Event publishing to multiple topics |

## 🏗️ Core Innovation

The library's core innovation is the `SharedTransportConnection` pattern that enables multiple Azure SDK clients to safely share persistent connections:

- **Semaphore-based limiting**: Controls concurrent operations per connection
- **Heap-optimized selection**: O(log n) optimal connection selection
- **Automatic lifecycle management**: Handles expiration and renewal
- **Lock-free design**: Minimizes contention in high-concurrency scenarios

## 🧪 Testing Support

Built-in pytest fixtures for easy testing:

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

## Links

- **Documentation**: [https://mulliganfunding.github.io/aio-azure-clients-toolbox/](https://mulliganfunding.github.io/aio-azure-clients-toolbox/)
- **Repository**: [GitHub Repository](https://github.com/MulliganFunding/aio-azure-clients-toolbox)

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

