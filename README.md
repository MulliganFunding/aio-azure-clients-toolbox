# Async Azure Clients Toolboox

This library includes wrappers for various async Azure Python clients. These are the ones we have used most commonly in our projects at Mulligan Funding.

This library has been open-sourced because it includes a "connection pooling" implementation that other developers may find useful or instructive ([see module here](./aio_azure_clients_toolbox/connection_pooling.py)).

In addition to the client-wrappers included here, we also have testing utilities to make this library more convenient to use with `pytest` (see below).

See below for introduction to the various modules available.

## Installation

```sh
pip install "aio-azure-clients-toolbox"

```

This will install the following libraries into your project (links go to examples below):

- azure-identity
- [azure-cosmos](#cosmos)
- [azure-eventgrid](#eventgrid)
- [azure-eventhub](#eventhub)
- [azure-servicebus](#service-bus)
- [azure-storage-blob](#azure-blobs)

**Note**: this library does not currently offer a way to select only some of these clients.

---

## Clients

This section describes the clients included here and offers suggestions on how to use them in your projects.

**Note**: All clients included here use a `DefaultAzureCredential` to connect to their resources.

**This is not configurable**.

**Note**: most of the examples below are primarily using the `Managed` clients (non-managed clients also exist). These will _open_ async connections and _keep_ them open in a connection-pooling. When connections are opened and closed they cannot be used. In addition, after opening, the clients must signal readiness by running their "ready" action. This typically means _sending_ a test message to confirm that the connection is live.

### Azure Blobs

This library includes an Azure Blob Storage client that contains common functionality such as the following:

- `upload_blob`
- `download_blob` (to bytes in memory)
- `download_blob_to_dir` (download a file to a directory)
- `delete_blob`
- `get_blob_sas_token`
- `get_blob_sas_token_list`
- `get_blob_sas_url`
- `get_blob_sas_url_list`

You can create and use this client like this:

```python
import aiofiles
import os
import tempfile

from azure.identity.aio import DefaultAzureCredential
from aio_azure_clients_toolbox import AzureBlobStorageClient
from aio_azure_clients_toolbox.clients.azure_blobs import AzureBlobError  # reexport


class AzureBlobStorageClient(AzureBlobStorageClient):
    CONTAINER_NAME = "some-container"
    __slots__ = [
        "file_workspace_dir",
    ]

    def __init__(
        self,
        az_storage_url: str,
        az_credential: DefaultAzureCredential,
        file_workspace_dir: str = "/tmp",
    ):
        super().__init__(
            az_storage_url,
            self.CONTAINER_NAME,
            az_credential
        )
        self.file_workspace_dir = file_workspace_dir

    async def download_document_to_workspace(self, name: str, storage_path: str) -> str:
        """
        Download Blob to a temporary directory.

        Tempdir is used to write to a directory without race conditions on cleanup/overwrite.

        Caller is responsible for cleaning up tempdir!
        """

        tempdir = tempfile.mkdtemp(dir=self.file_workspace_dir)
        save_path = os.path.join(tempdir, name)

        # Write file into file path in tempdir
        async with aiofiles.open(save_path, "wb") as fl:
            async with self.get_blob_client(  # This method returns a blob client
                storage_path
            ) as client:  # type: BlobClient
                stream = await client.download_blob()
                # Read data in chunks to avoid loading all into memory at once
                async for chunk in stream.chunks():
                    # `chunk` is a byte array
                    await fl.write(chunk)

        return save_path

```

### Cosmos

This library includes a Cosmos client that offers persistent connections up to a refresh timelimit.

You can use it like this:

```python
from aio_azure_clients_toolbox import ManagedCosmos

# This client can be subclassed
class Cosmos(ManagedCosmos):
    container_name: str = "documents"
    MatchConditions = MatchConditions

    def __init__(self, settings: Optional[config.Config] = None):
        super().__init__(
            settings.cosmos_endpoint,
            settings.cosmos_dbname,
            self.container_name,
            settings.az_credential(),
        )

    async def insert_doc(self, document: dict):
        """
        This method inserts a document
        """
        # This class provides an async context manager for connecting
        # to your container
        async with self.get_container_client() as client:
            return await client.create_item(body=document)

```

### Eventgrid

This library includes a custom event grid client that wraps the official azure event grid client. The primary advantage of this client is that it allows a single client instance to emit events to multiple topics. Additionally it supports both async/sync modes depending on how it's constructed.

Azure managed identities is required to use this client. Here is an async example for setting and emiting and event using the client:

```python
from aio_azure_clients_toolbox.clients.eventgrid import EventGridClient, EventGridTopicConfig, EventGridConfig

from azure.identity.aio import DefaultAzureCredential

eventgrid_config = EventGridConfig(
    [
        EventGridTopicConfig(
            "topic1", "https://topic1.azure.net/api/event",
        ),
        EventGridTopicConfig("topic2", "https://topic2.azure.net/api/event",
        ),
    ]
)

client = EventGridClient(eventgrid_config, async_credential=DefaultAzureCredential())
await client.async_emit_event(
      "topic2",
      "topic2-event-type",
      "topic2-subject",
      {},
  )
```

### Eventhub

```python
import json

from aio_azure_clients_toolbox.clients.eventhub import ManagedAzureEventhubProducer

client = ManagedEventhubProducer(
    eventhub_namespace,
    eventhub_name,
    az_credential(),
    eventhub_transport_type,
    ready_message='{"eventType": "connection-established"}'
)

async def send_something(event: dict):
    return await client.send_event(json.dumps(event))
```

### Service Bus

```python
import contextlib

from aio_azure_clients_toolbox import ManagedAzureServiceBusSender

sbus_client = AzureServiceBus(
    service_bus_namespace_url,
    service_bus_queue_name,
    az_credential()
)


# We can use this in our endpoints like this:
async def some_handler(request):
  await sbus_client.send_message("Some Message!")


# We can launch a listener like this:
async def run_service_bus_receiver(self):
  """Task-Worker processing message queue loop"""
  async with app.sbus_client.get_receiver() as receiver:
      async for msg in receiver:
        await handler_message(msg, receiver)

```

---

## Writing Tests

This library comes with a set of commonly-written (for us) pytest fixtures. You can load and use these in your `tests/conftest.py` module like this:

```python
pytest_plugins = [
    "aio_azure_clients_toolbox.testing_utils.fixtures",
]
```

After that, you can use the [fixtures provided here](./aio_azure_clients_toolbox/testing_utils/fixtures.py) as you would use any pytest fixture. Here's an example:

```python
# This test uses blob client fixture

async def test_get_blob_sas_token(absc, mock_azureblob, mocksas):
    mockgen, fake_token = mocksas
    _, mockblobc, _ = mock_azureblob
    mockblobc.account_name = "some-blobs"

    result = await absc.get_blob_sas_token("bla")
    assert result == fake_token

    result2 = await absc.get_blob_sas_url("bla")
    assert result2.endswith(f"some-blobs/bla?{fake_token}")

    # check mocked function to see what it was called with
    mockgen.call_count == 1
    call = mockgen.call_args_list[0]
    permission = call[1]["permission"]
    assert permission.read and not permission.write


async def test_download_blob(absc, mock_azureblob):
    _, _, set_return = mock_azureblob
    set_return.download_blob_returns(b"HEY")
    assert await absc.download_blob("some-blob") == b"HEY"


@pytest.fixture()
def cos_client(test_config):
    return cosmos.Cosmos(test_config)


# This test is using cosmos client fixture
async def test_insert_doc(cosmos_insertable, cos_client, document: dict):
    """Test insert document as expected"""
    # `cosmos_insertable` is a fixture provided by this library
    container_client, set_return = cosmos_insertable
    set_return("hello")
    result = await cos_client.insert_doc(document)
    assert result == "hello"
    call = container_client.method_calls[0]
    submitted = call[2]["body"]
    assert submitted == document

# This one uses our fake service bus fixture
async def test_send_message(sbus):
    await sbus.send_message("hey")
```
