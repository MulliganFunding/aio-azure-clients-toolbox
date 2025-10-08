# Installation

## Requirements

- Python 3.8+
- Azure subscription and appropriate service configurations

## Install from PyPI

```bash
pip install aio-azure-clients-toolbox
```

## Dependencies

Installing this package will include the following Azure SDK libraries:

| Package | Version | Purpose |
|---------|---------|---------|
| `azure-identity` | Latest | Azure authentication |
| `azure-cosmos` | Latest | Cosmos DB operations |
| `azure-eventgrid` | Latest | Event Grid publishing |
| `azure-eventhub` | Latest | Event Hub streaming |
| `azure-servicebus` | Latest | Service Bus messaging |
| `azure-storage-blob` | Latest | Blob storage operations |

Additional dependencies for connection pooling and async operations:

- `anyio` - Async I/O primitives
- Standard library modules for connection management

## Azure Authentication Setup

### Managed Clients (Connection Pooling)

Managed clients (those with connection pooling such as `ManagedCosmos`, `ManagedAzureEventhubProducer`, `ManagedAzureServiceBusSender`) now require a **CredentialFactory** instead of a direct credential instance. This is a callable that returns a new credential instance when needed:

```python
from azure.identity.aio import DefaultAzureCredential
from aio_azure_clients_toolbox import ManagedCosmos

# Use a lambda function that returns a new credential
cosmos_client = ManagedCosmos(
    endpoint="https://your-account.documents.azure.com:443/",
    dbname="your-database",
    container_name="your-container",
    credential_factory=lambda: DefaultAzureCredential()
)

# Or define a function
def get_credential():
    return DefaultAzureCredential()

cosmos_client = ManagedCosmos(
    endpoint="https://your-account.documents.azure.com:443/",
    dbname="your-database",
    container_name="your-container",
    credential_factory=get_credential
)
```

### Basic Clients

Basic clients (non-managed) continue to use `DefaultAzureCredential` directly:

```python
from aio_azure_clients_toolbox import AzureBlobStorageClient

blob_client = AzureBlobStorageClient(
    az_storage_url="https://your-storage.blob.core.windows.net",
    container_name="your-container",
    credentials=DefaultAzureCredential()  # Direct credential instance
)
```

### Authentication Methods

This library uses `DefaultAzureCredential` which attempts authentication methods in the following order:

1. **Environment Variables**: `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
2. **Managed Identity**: When running on Azure services
3. **Azure CLI**: When authenticated via `az login`
4. **Visual Studio Code**: When signed in to Azure account
5. **Azure PowerShell**: When authenticated via PowerShell

### Local Development

For local development, use Azure CLI:

```bash
az login
```

### Production Deployment

For production environments, use environment variables or managed identity:

```bash
export AZURE_CLIENT_ID="your-client-id"
export AZURE_CLIENT_SECRET="your-client-secret"
export AZURE_TENANT_ID="your-tenant-id"
```

### Container Environments

When deploying in containers, set environment variables in your deployment configuration:

```yaml
# docker-compose.yml example
environment:
  - AZURE_CLIENT_ID=${AZURE_CLIENT_ID}
  - AZURE_CLIENT_SECRET=${AZURE_CLIENT_SECRET}
  - AZURE_TENANT_ID=${AZURE_TENANT_ID}
```

## Service-Specific Configuration

Each Azure service requires specific configuration. Refer to the individual client documentation for service endpoints and permissions.

### Required Azure Permissions

Ensure your Azure credentials have appropriate permissions for the services you plan to use:

- **Blob Storage**: Storage Blob Data Contributor
- **Cosmos DB**: Cosmos DB Account Contributor
- **Event Grid**: Event Grid Data Sender
- **Event Hub**: Azure Event Hubs Data Sender
- **Service Bus**: Azure Service Bus Data Sender

## Verification

Verify the installation by importing the library:

```python
from aio_azure_clients_toolbox import ManagedCosmos
print("Installation successful")
```

## Development Installation

For development, clone the repository and install in editable mode:

```bash
git clone https://github.com/MulliganFunding/aio-azure-clients-toolbox.git
cd aio-azure-clients-toolbox
pip install -e .
```