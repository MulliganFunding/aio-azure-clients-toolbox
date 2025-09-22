# AIO Azure Clients Toolbox

Async Python connection pooling library for Azure SDK clients.

## Overview

This library provides wrapper classes for Azure SDK clients with built-in connection pooling capabilities. The primary focus is maintaining persistent async connections to Azure services while managing connection lifecycle automatically.

## Key Features

- **Connection Pooling**: Persistent connections with configurable pool sizes and idle timeouts
- **Managed Clients**: Automatic connection lifecycle management for Azure services
- **Azure SDK Integration**: Wraps official Azure SDK clients for Python
- **Testing Utilities**: Pytest fixtures for mocking Azure services
- **Async/Await Support**: Built for modern async Python applications

## Supported Azure Services

| Service | Client Classes | Description |
|---------|---------------|-------------|
| Azure Blob Storage | `AzureBlobStorageClient` | File upload/download with SAS token support |
| Cosmos DB | `Cosmos`, `ManagedCosmos` | Document database operations with connection pooling |
| Event Grid | `EventGridClient` | Event publishing to multiple topics |
| Event Hub | `Eventhub`, `ManagedAzureEventhubProducer` | Event streaming with persistent connections |
| Service Bus | `AzureServiceBus`, `ManagedAzureServiceBusSender` | Message queuing with connection management |

## Authentication

All clients use `DefaultAzureCredential` from the Azure Identity library. This credential type automatically selects the appropriate authentication method based on the environment.

## Quick Start

Install the library:

```bash
pip install aio-azure-clients-toolbox
```

Basic usage with a managed Cosmos DB client:

```python
from azure.identity.aio import DefaultAzureCredential
from aio_azure_clients_toolbox import ManagedCosmos

# Initialize client with connection pooling
cosmos_client = ManagedCosmos(
    endpoint="https://your-cosmos.documents.azure.com:443/",
    dbname="your-database",
    container_name="your-container",
    credential=DefaultAzureCredential()
)

# Use async context manager for operations
async with cosmos_client.get_container_client() as container:
    result = await container.create_item(body={"id": "1", "data": "example"})
```

## Architecture

The library implements two types of clients:

- **Basic Clients**: Direct wrappers around Azure SDK clients
- **Managed Clients**: Enhanced versions with connection pooling via `AbstractorConnector`

Managed clients maintain a pool of connections that can be shared across multiple concurrent operations, reducing connection overhead and improving performance.

## Next Steps

- [Installation](installation.md) - Setup and dependencies
- [Connection Pooling](connection-pooling.md) - Understanding the pooling mechanism
- [Clients](clients/cosmos.md) - Service-specific documentation
- [Testing](testing/fixtures.md) - Using the testing utilities