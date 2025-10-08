# Testing Examples

Simple examples showing how to use the testing fixtures provided by this library

## Setup

Add to your `conftest.py`:

```python
pytest_plugins = [
    "aio_azure_clients_toolbox.testing_utils.fixtures",
]
```

## Azure Blob Storage

### Basic Operations

```python
async def test_upload_blob(absc, mock_azureblob):
    container_client, mock_blob_client, set_return = mock_azureblob

    # Configure expected upload response
    set_return.upload_blob_returns({"status": "uploaded"})

    # Test upload
    result = await absc.upload_blob("test.txt", b"content")

    assert result == {"status": "uploaded"}

async def test_download_blob(absc, mock_azureblob):
    container_client, mock_blob_client, set_return = mock_azureblob

    # Configure download response
    set_return.download_blob_returns(b"file content")

    # Test download
    content = await absc.download_blob("test.txt")

    assert content == b"file content"

async def test_list_blobs(absc, mock_azureblob):
    from azure.storage.blob import BlobProperties

    container_client, mock_blob_client, set_return = mock_azureblob

    # Configure list response
    mock_blobs = [
        BlobProperties(name="file1.txt", size=100),
        BlobProperties(name="file2.txt", size=200),
    ]
    set_return.list_blobs_returns(mock_blobs)

    # Test listing
    blobs = [blob async for blob in absc.list_blobs()]

    assert len(blobs) == 2
    assert blobs[0].name == "file1.txt"
```

### SAS Token Generation

```python
async def test_sas_token(absc, mock_azureblob, mocksas):
    mockgen, fake_token = mocksas
    container_client, mock_blob_client, _ = mock_azureblob
    mock_blob_client.account_name = "teststorage"

    # Test token generation
    token = await absc.get_blob_sas_token("test.txt")

    assert token == fake_token

async def test_sas_url(absc, mock_azureblob, mocksas):
    mockgen, fake_token = mocksas
    container_client, mock_blob_client, _ = mock_azureblob
    mock_blob_client.account_name = "teststorage"

    # Test URL generation
    url = await absc.get_blob_sas_url("test.txt")

    assert fake_token in url
    assert "test.txt" in url
```

## Cosmos DB

### Document Operations

```python
async def test_create_document(cosmos_insertable):
    container_client, set_return = cosmos_insertable

    test_doc = {"id": "test-1", "name": "Test Document"}
    set_return(test_doc)

    result = await container_client.create_item(body=test_doc)

    assert result == test_doc

async def test_read_document(cosmos_readable):
    container_client, set_return = cosmos_readable

    expected = {"id": "test-1", "name": "Test Document"}
    set_return(expected)

    result = await container_client.read_item(item="test-1", partition_key="test-1")

    assert result == expected

async def test_update_document(cosmos_updatable):
    container_client, set_return = cosmos_updatable

    updated_doc = {"id": "test-1", "name": "Updated Document"}
    set_return(updated_doc)

    result = await container_client.replace_item(item="test-1", body=updated_doc)

    assert result == updated_doc

async def test_delete_document(cosmos_deletable):
    container_client, set_return = cosmos_deletable

    set_return(None)

    await container_client.delete_item(item="test-1", partition_key="test-1")
    # No exception means success
```

### Query Operations

```python
async def test_query_documents(cosmos_queryable):
    container_client, set_return = cosmos_queryable

    expected_docs = [
        {"id": "1", "name": "Doc 1"},
        {"id": "2", "name": "Doc 2"}
    ]
    set_return(None, side_effect=expected_docs)

    docs = []
    async for doc in container_client.query_items("SELECT * FROM c"):
        docs.append(doc)

    assert docs == expected_docs
```

## Service Bus

### Message Operations

```python
async def test_send_message(sbus):
    message = "test message"

    await sbus.send_message(message)

    assert message in sbus.sent_messages

async def test_schedule_message(managed_sbus):
    await managed_sbus.send_message("scheduled message", delay=300)

    # Verify scheduled message call
    managed_sbus._sender.schedule_messages.assert_called_once()
```

## Event Hub

### Event Publishing

```python
async def test_send_event(mockehub):
    from aio_azure_clients_toolbox.clients.eventhub import Eventhub

    client = Eventhub("namespace", "hub", lambda: mock.AsyncMock())

    await client.send_event("test event")

    mockehub.add.assert_called_once_with("test event")
    mockehub.send_batch.assert_called_once()
```

## Event Grid

### Event Publishing

```python
async def test_publish_event(mockegrid):
    from aio_azure_clients_toolbox.clients.eventgrid import EventGridClient

    sync_client, async_client = mockegrid

    client = EventGridClient("https://topic.eventgrid.azure.net/api/events")
    client.send_event({"data": "test"})

    sync_client.send.assert_called_once()
```