# Testing Examples

Practical examples for testing applications that use aio-azure-clients-toolbox.

## Unit Testing Patterns

### Testing Service Classes

```python
import pytest
from unittest.mock import AsyncMock
from your_app.services import UserService

class TestUserService:
    @pytest.fixture
    def user_service(self, cosmos_insertable):
        """Create UserService with mocked Cosmos client."""
        container_client, set_return = cosmos_insertable

        # Create service with mocked dependencies
        service = UserService(cosmos_client=container_client)
        service.set_return = set_return  # For test configuration
        return service

    async def test_create_user(self, user_service):
        """Test user creation."""
        # Configure mock response
        expected_result = {"id": "user-123", "status": "created"}
        user_service.set_return(expected_result)

        # Test user creation
        user_data = {"name": "John Doe", "email": "john@example.com"}
        result = await user_service.create_user(user_data)

        assert result == expected_result

    async def test_get_user_not_found(self, user_service):
        """Test handling of user not found."""
        # Configure mock to raise exception
        from azure.cosmos import exceptions
        user_service.set_return.side_effect = exceptions.CosmosResourceNotFoundError()

        # Test user retrieval
        result = await user_service.get_user("nonexistent-id")

        assert result is None
```

### Testing Event Publishing

```python
class TestEventPublisher:
    @pytest.fixture
    def mock_eventgrid_client(self):
        """Mock Event Grid client."""
        mock_client = AsyncMock()
        mock_client.async_emit_event = AsyncMock()
        return mock_client

    @pytest.fixture
    def event_publisher(self, mock_eventgrid_client):
        """Create EventPublisher with mocked client."""
        from your_app.events import EventPublisher
        return EventPublisher(mock_eventgrid_client)

    async def test_publish_user_created_event(self, event_publisher, mock_eventgrid_client):
        """Test user created event publishing."""
        user_data = {"id": "user-123", "email": "test@example.com"}

        await event_publisher.publish_user_created(user_data)

        # Verify event was published with correct parameters
        mock_eventgrid_client.async_emit_event.assert_called_once_with(
            topic_name="user-events",
            event_type="user.created",
            subject="users/user-123",
            data=user_data
        )
```

### Testing Blob Storage Operations

```python
class TestDocumentService:
    async def test_upload_document(self, absc, mock_azureblob):
        """Test document upload."""
        _, mock_blob_client, set_return = mock_azureblob

        # Configure mock response
        expected_result = {"url": "https://storage.blob.core.windows.net/docs/test.pdf"}
        set_return.upload_blob_returns(expected_result)

        # Test document upload
        document_content = b"PDF content"
        result = await absc.upload_blob("documents/test.pdf", document_content)

        assert result == expected_result
        mock_blob_client.upload_blob.assert_called_once()

    async def test_generate_sas_url(self, absc, mock_azureblob, mocksas):
        """Test SAS URL generation."""
        mockgen, fake_token = mocksas
        _, mockblobc, _ = mock_azureblob
        mockblobc.account_name = "teststorage"

        # Test SAS URL generation
        sas_url = await absc.get_blob_sas_url("documents/test.pdf")

        assert fake_token in sas_url
        assert "teststorage" in sas_url
        assert "documents/test.pdf" in sas_url
```

## Integration Testing

### Multi-Service Integration

```python
@pytest.mark.integration
class TestOrderProcessingWorkflow:
    @pytest.fixture
    def order_processor(self, cosmos_insertable, absc, mock_eventgrid_client):
        """Create order processor with all dependencies."""
        from your_app.order_processor import OrderProcessor

        cosmos_client, set_cosmos_return = cosmos_insertable

        processor = OrderProcessor(
            cosmos_client=cosmos_client,
            blob_client=absc,
            event_client=mock_eventgrid_client
        )
        processor.set_cosmos_return = set_cosmos_return
        return processor

    async def test_complete_order_workflow(self, order_processor, mock_azureblob):
        """Test complete order processing workflow."""
        _, _, set_blob_return = mock_azureblob

        # Configure mock responses
        order_processor.set_cosmos_return({"id": "order-123", "status": "processed"})
        set_blob_return.upload_blob_returns({"url": "https://storage/receipt.pdf"})

        # Process order
        order_data = {
            "id": "order-123",
            "customer_id": "customer-456",
            "items": [{"sku": "ITEM-001", "quantity": 2}]
        }

        result = await order_processor.process_order(order_data)

        # Verify order was saved to Cosmos
        assert result["id"] == "order-123"

        # Verify receipt was uploaded to blob storage
        # (Check mock_azureblob calls)

        # Verify events were published
        # (Check mock_eventgrid_client calls)
```

### Database State Testing

```python
class TestUserRepository:
    @pytest.fixture
    def user_repository(self, cosmos_insertable):
        """Create user repository with mocked Cosmos."""
        container_client, set_return = cosmos_insertable

        from your_app.repositories import UserRepository
        repo = UserRepository(container_client)
        repo.set_return = set_return
        return repo

    async def test_user_crud_operations(self, user_repository):
        """Test complete CRUD workflow."""
        # Test data
        user_data = {
            "id": "user-123",
            "name": "John Doe",
            "email": "john@example.com"
        }

        # Test Create
        user_repository.set_return(user_data)
        created_user = await user_repository.create_user(user_data)
        assert created_user["id"] == "user-123"

        # Test Read
        user_repository.set_return(user_data)
        retrieved_user = await user_repository.get_user("user-123")
        assert retrieved_user["email"] == "john@example.com"

        # Test Update
        updated_data = {**user_data, "name": "John Smith"}
        user_repository.set_return(updated_data)
        updated_user = await user_repository.update_user("user-123", {"name": "John Smith"})
        assert updated_user["name"] == "John Smith"

        # Test Delete
        user_repository.set_return(None)
        await user_repository.delete_user("user-123")
        # Verify delete was called (check mock calls)
```

## Property-Based Testing

```python
from hypothesis import given, strategies as st

class TestDataValidation:
    @given(st.text(min_size=1, max_size=100))
    async def test_document_name_validation(self, document_name, absc, mock_azureblob):
        """Property-based test for document name validation."""
        _, _, set_return = mock_azureblob
        set_return.upload_blob_returns({"status": "success"})

        # Test that any valid string can be used as document name
        content = b"test content"

        try:
            result = await absc.upload_blob(document_name, content)
            assert result["status"] == "success"
        except ValueError:
            # Some characters might be invalid for blob names
            # This is expected behavior
            pass

    @given(st.dictionaries(
        keys=st.text(min_size=1, max_size=50),
        values=st.one_of(st.text(), st.integers(), st.floats(), st.booleans()),
        min_size=1,
        max_size=10
    ))
    async def test_cosmos_document_structure(self, document_data, cosmos_insertable):
        """Test that various document structures can be stored."""
        container_client, set_return = cosmos_insertable

        # Add required id field
        document_data["id"] = "test-doc"

        set_return(document_data)

        # Test document creation with random structure
        result = await container_client.create_item(body=document_data)
        assert result == document_data
```

## Performance Testing

```python
import asyncio
import time

class TestPerformance:
    async def test_concurrent_cosmos_operations(self, cosmos_insertable):
        """Test concurrent Cosmos DB operations."""
        container_client, set_return = cosmos_insertable

        # Configure mock to simulate realistic response times
        async def mock_create_item(body=None, **kwargs):
            await asyncio.sleep(0.01)  # Simulate 10ms latency
            return {"id": body["id"], "status": "created"}

        container_client.create_item.side_effect = mock_create_item

        # Create multiple documents concurrently
        documents = [
            {"id": f"doc-{i}", "data": f"content-{i}"}
            for i in range(100)
        ]

        start_time = time.time()

        results = await asyncio.gather(*[
            container_client.create_item(body=doc)
            for doc in documents
        ])

        end_time = time.time()
        duration = end_time - start_time

        # Verify all documents were processed
        assert len(results) == 100

        # Performance assertion (should be much faster than serial execution)
        assert duration < 2.0  # Should complete in under 2 seconds

    async def test_blob_upload_throughput(self, absc, mock_azureblob):
        """Test blob upload throughput."""
        _, _, set_return = mock_azureblob

        # Mock fast upload responses
        async def mock_upload(data, **kwargs):
            await asyncio.sleep(0.001)  # 1ms simulated upload time
            return {"status": "uploaded", "size": len(data)}

        set_return.upload_blob_side_effect = mock_upload

        # Upload multiple files concurrently
        files = [
            (f"file-{i}.txt", f"content-{i}" * 100)  # ~900 bytes per file
            for i in range(50)
        ]

        start_time = time.time()

        results = await asyncio.gather(*[
            absc.upload_blob(filename, content.encode())
            for filename, content in files
        ])

        end_time = time.time()
        duration = end_time - start_time

        assert len(results) == 50
        assert duration < 1.0  # Should complete quickly with mocked responses
```

## Error Condition Testing

```python
class TestErrorHandling:
    async def test_cosmos_connection_failure(self, cosmos_insertable):
        """Test handling of Cosmos DB connection failures."""
        container_client, set_return = cosmos_insertable

        from azure.cosmos import exceptions

        # Simulate connection failure
        set_return.side_effect = exceptions.CosmosHttpResponseError(
            status_code=503,
            message="Service temporarily unavailable"
        )

        # Test that service handles the error gracefully
        with pytest.raises(exceptions.CosmosHttpResponseError):
            await container_client.create_item(body={"id": "test"})

    async def test_blob_storage_quota_exceeded(self, absc, mock_azureblob):
        """Test handling of storage quota exceeded."""
        _, _, set_return = mock_azureblob

        from azure.core.exceptions import HttpResponseError

        # Simulate quota exceeded error
        set_return.side_effect = HttpResponseError(
            "Storage quota exceeded",
            response=None
        )

        with pytest.raises(HttpResponseError):
            await absc.upload_blob("large-file.bin", b"x" * 1024 * 1024)

    async def test_event_grid_rate_limiting(self, mock_eventgrid_client):
        """Test handling of Event Grid rate limiting."""
        from azure.core.exceptions import HttpResponseError

        # Simulate rate limiting
        mock_eventgrid_client.async_emit_event.side_effect = HttpResponseError(
            "Rate limit exceeded",
            response=None
        )

        from your_app.events import EventPublisher
        publisher = EventPublisher(mock_eventgrid_client)

        with pytest.raises(HttpResponseError):
            await publisher.publish_user_created({"id": "user-123"})
```

## Test Configuration

### Custom Test Fixtures

```python
# conftest.py
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def test_config():
    """Provide test configuration."""
    return {
        "cosmos_endpoint": "https://test-cosmos.documents.azure.com:443/",
        "cosmos_database": "test-db",
        "storage_account_url": "https://teststorage.blob.core.windows.net",
        "eventgrid_topics": {
            "user-events": "https://test-events.azure.net/api/events"
        }
    }

@pytest.fixture
def mock_credential():
    """Provide mock Azure credential."""
    credential = AsyncMock()
    credential.get_token = AsyncMock(return_value=AsyncMock(token="fake-token"))
    return credential

@pytest.fixture
def application_service(test_config, cosmos_insertable, absc, mock_eventgrid_client):
    """Provide fully configured application service for testing."""
    from your_app.services import ApplicationService

    cosmos_client, set_cosmos_return = cosmos_insertable

    service = ApplicationService(
        config=test_config,
        cosmos_client=cosmos_client,
        blob_client=absc,
        event_client=mock_eventgrid_client
    )

    # Provide test helpers
    service.set_cosmos_return = set_cosmos_return

    return service
```

### Pytest Configuration

```python
# pytest.ini or pyproject.toml
[tool.pytest.ini_options]
addopts = "-v --tb=short --strict-markers"
markers = [
    "unit: Unit tests",
    "integration: Integration tests",
    "performance: Performance tests",
    "slow: Slow running tests"
]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

### Running Tests

```bash
# Run all tests
pytest

# Run only unit tests
pytest -m unit

# Run tests with coverage
pytest --cov=your_app --cov-report=html

# Run tests in parallel
pytest -n auto

# Run specific test file
pytest tests/test_user_service.py

# Run with verbose output
pytest -v -s
```