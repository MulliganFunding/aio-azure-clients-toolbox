# Testing Fixtures

Pytest fixtures for mocking Azure services and testing client implementations.

## Setup

Load fixtures in your `tests/conftest.py`:

```python
pytest_plugins = [
    "aio_azure_clients_toolbox.testing_utils.fixtures",
]
```

## Available Fixtures

### Azure Blob Storage

#### `absc` (Azure Blob Storage Client)

Provides a configured `AzureBlobStorageClient` instance for testing.

#### `mock_azureblob`

Mocks Azure Blob Storage operations.

**Returns**: `(container_client, mock_blob_client, set_return_function)`

#### `mocksas`

Mocks SAS token generation.

**Returns**: `(mock_generator, fake_token)`

### Cosmos DB

#### `cosmos_insertable`

Mocks Cosmos DB container operations.

**Returns**: `(mock_container_client, set_return_function)`

### Service Bus

#### `sbus`

Provides a fake Service Bus client for testing message operations.

## Usage Examples

### Blob Storage Testing

```python
# Test blob upload
async def test_upload_blob(absc, mock_azureblob):
    container_client, mock_blob_client, set_return = mock_azureblob

    # Configure mock response
    set_return.upload_blob_returns("mock-response")

    # Test upload
    result = await absc.upload_blob("test.txt", b"content")

    # Verify call
    assert mock_blob_client.upload_blob.called
    assert result == "mock-response"

# Test blob download
async def test_download_blob(absc, mock_azureblob):
    container_client, mock_blob_client, set_return = mock_azureblob

    # Mock download response
    set_return.download_blob_returns(b"file content")

    # Test download
    content = await absc.download_blob("test.txt")

    assert content == b"file content"

# Test blob listing
async def test_list_blobs(absc, mock_azureblob):
    container_client, mock_blob_client, set_return = mock_azureblob

    # Mock list response
    mock_blobs = [
        BlobProperties(name="file1.txt", size=100),
        BlobProperties(name="file2.txt", size=200),
    ]
    set_return.list_blobs_returns(mock_blobs)

    # Test listing
    blobs = [blob async for blob in absc.list_blobs()]

    assert len(blobs) == 2
    assert blobs[0].name == "file1.txt"

# Test SAS token generation
async def test_get_blob_sas_token(absc, mock_azureblob, mocksas):
    mockgen, fake_token = mocksas
    container_client, mock_blob_client, _ = mock_azureblob
    mock_blob_client.account_name = "teststorage"

    # Test token generation
    result = await absc.get_blob_sas_token("test.txt")

    assert result == fake_token
    assert mockgen.call_count == 1

    # Verify SAS URL generation
    sas_url = await absc.get_blob_sas_url("test.txt")
    assert sas_url.endswith(f"teststorage/test.txt?{fake_token}")
```

### Cosmos DB Testing

```python
@pytest.fixture
def cosmos_client(test_config):
    """Application-specific Cosmos client fixture."""
    return CosmosDocumentStore(test_config)

async def test_insert_document(cosmos_insertable, cosmos_client):
    container_client, set_return = cosmos_insertable

    # Configure mock response
    set_return("success-response")

    # Test document insertion
    document = {"id": "test-doc", "data": "test-data"}
    result = await cosmos_client.insert_document(document)

    assert result == "success-response"

    # Verify the call
    call = container_client.method_calls[0]
    submitted_doc = call[2]["body"]
    assert submitted_doc == document

async def test_query_documents(cosmos_insertable, cosmos_client):
    container_client, set_return = cosmos_insertable

    # Mock query results
    mock_results = [{"id": "1", "name": "test"}]
    set_return.query_items_returns(mock_results)

    # Test query
    results = await cosmos_client.find_documents_by_name("test")

    assert results == mock_results
```

### Service Bus Testing

```python
async def test_send_message(sbus):
    """Test Service Bus message sending."""
    message = "test message"

    # Send message using fake client
    await sbus.send_message(message)

    # Verify message was "sent" (stored in fake client)
    assert message in sbus.sent_messages

async def test_message_handler(sbus):
    """Test message processing logic."""
    # Add message to fake queue
    test_message = {"event_type": "user_created", "user_id": 123}
    sbus.add_message(json.dumps(test_message))

    # Process messages
    processed_messages = []

    async def message_handler(message):
        data = json.loads(message)
        processed_messages.append(data)

    await sbus.process_messages(message_handler)

    assert len(processed_messages) == 1
    assert processed_messages[0] == test_message
```

### Custom Fixture Creation

```python
# conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_event_hub():
    """Custom Event Hub mock fixture."""
    mock_producer = AsyncMock()
    mock_producer.send_event = AsyncMock()
    mock_producer.close = AsyncMock()

    return mock_producer

@pytest.fixture
def event_hub_client(mock_event_hub, monkeypatch):
    """Event Hub client with mocked dependencies."""
    from aio_azure_clients_toolbox.clients.eventhub import ManagedAzureEventhubProducer

    # Mock the create method to return our mock
    async def mock_create(self):
        return mock_event_hub

    monkeypatch.setattr(
        ManagedAzureEventhubProducer,
        'create',
        mock_create
    )

    return ManagedAzureEventhubProducer(
        eventhub_namespace="test-namespace",
        eventhub_name="test-hub",
        credential=AsyncMock()
    )
```

### Integration Test Patterns

```python
@pytest.mark.integration
async def test_end_to_end_document_flow(cosmos_client, blob_client):
    """Integration test using multiple Azure services."""

    # Store document in Cosmos
    document = {"id": "test-1", "file_path": "documents/test.pdf"}
    await cosmos_client.create_document(document)

    # Upload associated file to blob storage
    file_content = b"PDF content here"
    await blob_client.upload_blob(document["file_path"], file_content)

    # Retrieve and verify
    stored_doc = await cosmos_client.get_document("test-1")
    stored_file = await blob_client.download_blob(stored_doc["file_path"])

    assert stored_doc["id"] == "test-1"
    assert stored_file == file_content
```

## Mock Configuration

### Configuring Return Values

```python
# Configure multiple return values
set_return.create_item_returns(["result1", "result2", "result3"])

# Configure side effects
set_return.create_item_side_effect(ValueError("Test error"))

# Configure conditional responses
def conditional_response(item):
    if item.get("should_fail"):
        raise Exception("Configured failure")
    return {"id": item["id"], "status": "created"}

set_return.create_item_side_effect(conditional_response)

# For blob storage operations
set_return.download_blob_returns(b"mock file content")
set_return.list_blobs_returns([
    BlobProperties(name="file1.txt", size=100),
    BlobProperties(name="file2.txt", size=200)
])
```

### Verifying Mock Calls

```python
# Check call count
assert mock_container.create_item.call_count == 3

# Check call arguments
calls = mock_container.create_item.call_args_list
first_call_args = calls[0][1]  # kwargs
assert first_call_args["body"]["id"] == "expected-id"

# Check call order
mock_container.assert_has_calls([
    call.create_item(body={"id": "1"}),
    call.create_item(body={"id": "2"})
])
```

## Test Organization

### Fixture Scoping

```python
# Session-scoped for expensive setup
@pytest.fixture(scope="session")
def azure_config():
    return AzureTestConfig()

# Function-scoped for test isolation
@pytest.fixture
def clean_cosmos_client(azure_config):
    client = CosmosClient(azure_config)
    yield client
    # Cleanup after test
    await client.cleanup_test_data()
```

### Parameterized Tests

```python
@pytest.mark.parametrize("document,expected", [
    ({"id": "1", "type": "user"}, "user-created"),
    ({"id": "2", "type": "product"}, "product-created"),
    ({"id": "3", "type": "order"}, "order-created")
])
async def test_document_processing(cosmos_insertable, document, expected):
    container_client, set_return = cosmos_insertable
    set_return(expected)

    result = await process_document(container_client, document)
    assert result == expected
```