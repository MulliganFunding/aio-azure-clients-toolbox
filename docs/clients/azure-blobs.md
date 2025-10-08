# Azure Blob Storage Client

Client for Azure Blob Storage operations with SAS token support and async file operations.

## AzureBlobStorageClient

Primary client for blob storage operations.

### Constructor

```python
AzureBlobStorageClient(
    az_storage_url: str,
    container_name: str,
    credential: DefaultAzureCredential
)
```

### Parameters

- **az_storage_url**: Azure Storage account URL
- **container_name**: Target blob container name
- **credential**: Azure authentication credential

### Core Methods

#### upload_blob

```python
async def upload_blob(
    blob_name: str,
    data: bytes | str,
    overwrite: bool = True
) -> BlobClient
```

Upload data to blob storage.

#### download_blob

```python
async def download_blob(blob_name: str) -> bytes
```

Download blob content to memory as bytes.

#### download_blob_to_dir

```python
async def download_blob_to_dir(
    blob_name: str,
    local_dir: str
) -> str
```

Download blob to local directory, returns file path.

#### delete_blob

```python
async def delete_blob(blob_name: str) -> None
```

Delete blob from storage.

#### list_blobs

```python
async def list_blobs(
    prefix: str | None = None,
    **kwargs
) -> AsyncGenerator[BlobProperties]
```

List blobs in the container with optional prefix filtering.

#### get_blob_sas_token

```python
async def get_blob_sas_token(
    blob_name: str,
    permission: BlobSasPermissions = None,
    expiry_hours: int = 24
) -> str
```

Generate SAS token for blob access.

#### get_blob_sas_url

```python
async def get_blob_sas_url(
    blob_name: str,
    permission: BlobSasPermissions = None,
    expiry_hours: int = 24
) -> str
```

Generate complete SAS URL for blob access.

## Usage Examples

### Basic Operations

```python
from azure.identity.aio import DefaultAzureCredential
from aio_azure_clients_toolbox import AzureBlobStorageClient

# Initialize client
blob_client = AzureBlobStorageClient(
    az_storage_url="https://yourstorageaccount.blob.core.windows.net",
    container_name="documents",
    credential=DefaultAzureCredential()
)

# Upload file
with open("document.pdf", "rb") as file:
    data = file.read()
    await blob_client.upload_blob("documents/document.pdf", data)

# Download file
content = await blob_client.download_blob("documents/document.pdf")

# Download to directory
file_path = await blob_client.download_blob_to_dir(
    "documents/document.pdf",
    "/tmp/downloads"
)

# Delete file
await blob_client.delete_blob("documents/document.pdf")

# List all blobs
async for blob in blob_client.list_blobs():
    print(f"Blob: {blob.name}, Size: {blob.size}")

# List blobs with prefix
async for blob in blob_client.list_blobs(prefix="documents/"):
    print(f"Document: {blob.name}")
```

### SAS Token Generation

```python
from azure.storage.blob import BlobSasPermissions

# Read-only SAS token
read_token = await blob_client.get_blob_sas_token(
    "documents/document.pdf",
    permission=BlobSasPermissions(read=True),
    expiry_hours=1
)

# Complete SAS URL
sas_url = await blob_client.get_blob_sas_url(
    "documents/document.pdf",
    permission=BlobSasPermissions(read=True),
    expiry_hours=24
)
```

### Batch Operations

```python
# Upload multiple files
files = [("file1.txt", b"content1"), ("file2.txt", b"content2")]

import asyncio

async def upload_file(name, content):
    return await blob_client.upload_blob(name, content)

results = await asyncio.gather(*[
    upload_file(name, content) for name, content in files
])

# Generate multiple SAS URLs
blob_names = ["file1.txt", "file2.txt", "file3.txt"]
sas_urls = await blob_client.get_blob_sas_url_list(
    blob_names,
    permission=BlobSasPermissions(read=True),
    expiry_hours=24
)
```

### Subclassing Example

```python
import tempfile
import os
import aiofiles
from azure.storage.blob.aio import BlobClient

class DocumentStorageClient(AzureBlobStorageClient):
    CONTAINER_NAME = "documents"

    def __init__(self, storage_url: str, credential, workspace_dir: str = "/tmp"):
        super().__init__(storage_url, self.CONTAINER_NAME, credential)
        self.workspace_dir = workspace_dir

    async def download_document_to_workspace(
        self,
        document_name: str,
        storage_path: str
    ) -> str:
        """Download document to temporary workspace directory."""

        # Create temporary directory
        tempdir = tempfile.mkdtemp(dir=self.workspace_dir)
        save_path = os.path.join(tempdir, document_name)

        # Stream download to avoid memory issues with large files
        async with aiofiles.open(save_path, "wb") as file:
            async with self.get_blob_client(storage_path) as client:
                stream = await client.download_blob()
                async for chunk in stream.chunks():
                    await file.write(chunk)

        return save_path

    async def upload_document_with_metadata(
        self,
        blob_name: str,
        data: bytes,
        metadata: dict
    ):
        """Upload document with custom metadata."""
        async with self.get_blob_client(blob_name) as client:
            return await client.upload_blob(
                data,
                overwrite=True,
                metadata=metadata
            )
```

### Error Handling

```python
from azure.core.exceptions import ResourceNotFoundError, ClientAuthenticationError

try:
    content = await blob_client.download_blob("nonexistent.txt")
except ResourceNotFoundError:
    print("Blob not found")
except ClientAuthenticationError:
    print("Authentication failed")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Configuration

### Storage Account Setup

Ensure your storage account has:

- Blob service enabled
- Container created with appropriate access level
- RBAC permissions: "Storage Blob Data Contributor"

### Connection String Alternative

For environments using connection strings:

```python
# Note: This library uses DefaultAzureCredential
# For connection string support, use Azure SDK directly
from azure.storage.blob.aio import BlobServiceClient

blob_service = BlobServiceClient.from_connection_string(connection_string)
```

### Performance Considerations

- Use streaming for large files to avoid memory issues
- Batch operations when possible to reduce API calls
- Consider blob access tiers for cost optimization
- Monitor storage account rate limits