from unittest import mock

import pytest
from azure.cosmos import aio as az_cosmos_client
from azure.eventgrid import EventGridPublisherClient
from azure.eventgrid.aio import EventGridPublisherClient as AsyncEventGridPublisherClient
from azure.eventhub.aio import EventHubProducerClient
from azure.servicebus.aio import ServiceBusClient
from azure.storage.blob.aio import BlobClient

from aio_azure_clients_toolbox import clients


@pytest.fixture(scope="session")
def monkeysession():
    with pytest.MonkeyPatch.context() as mp:
        yield mp


def make_async_ctx_mgr(mock_thing):
    something = mock_thing

    class WithAsyncContextManager:
        def __getattr__(self, key):
            return getattr(something, key)

        async def __aenter__(self, *args, **kwargs):
            return something

        async def __aexit__(self, *args, **kwargs):
            pass

    return WithAsyncContextManager()


class AsyncIterImplementation:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.return_value = None
        self.side_effect = None
        self._has_returned = False
        self._is_iter = None

    async def _call__(self):
        if self.side_effect and isinstance(self.side, Exception):
            raise self.side_effect
        if self.side_effect is not None and isinstance(self.side_effect, Exception):
            raise self.side_effect
        if hasattr(self.side_effect, "__iter__"):
            self._is_iter = iter(self.side_effect)

        return self.return_value

    def __aiter__(self):
        if self.side_effect is not None and isinstance(self.side_effect, Exception):
            raise self.side_effect
        if hasattr(self.side_effect, "__iter__"):
            self._is_iter = iter(self.side_effect)
        return self

    async def __anext__(self):
        if self._is_iter:
            try:
                return next(self._is_iter)
            except StopIteration as exc:
                raise StopAsyncIteration from exc
        elif self._has_returned:
            raise StopAsyncIteration
        self._has_returned = True
        return self.return_value


@pytest.fixture(autouse=True)
def mocksas():
    with mock.patch.object(clients.azure_blobs, "generate_blob_sas", return_value="fake-token") as mockgen:
        yield mockgen, "fake-token"


@pytest.fixture(autouse=True)
async def mock_azureblob(monkeypatch):  # type: ignore
    """Mock out Azure Blob Service client"""
    mockblobc = mock.MagicMock(BlobClient)
    # Parent: also, container client, delivers a blob client
    inner_client = mock.Mock()
    mockbsc = mock.Mock(return_value=make_async_ctx_mgr(inner_client))
    inner_client.get_container_client = mock.Mock(return_value=make_async_ctx_mgr(inner_client))
    inner_client.get_blob_client = mock.PropertyMock(return_value=mockblobc)
    inner_client.delete_blobs = mock.AsyncMock()
    monkeypatch.setattr(clients.azure_blobs, "BlobServiceClient", mockbsc)
    inner_client.get_user_delegation_key = mock.AsyncMock()
    mockblobc.upload_blob_from_url = mock.AsyncMock()
    mockblobc.upload_blob = mock.AsyncMock()
    mockblobc.delete_blob = mock.AsyncMock()

    def set_download_return(return_value, side_effect=None):
        """
        Set the return value for the download_blob method and list_blobs method.
        """
        # For `async for` with `download_blob`
        async_downloader = AsyncIterImplementation()
        async_downloader.return_value = return_value
        if side_effect is not None:
            async_downloader.side_effect = side_effect

        chunks_thing = mock.Mock(
            **{
                "readall": mock.AsyncMock(return_value=return_value),
                "chunks.return_value": async_downloader,
            }
        )
        mockblobc.download_blob.return_value = chunks_thing

    def set_list_blobs_return(list_or_side_effect):
        # For `async for` with `list_blobs`
        async_lister = AsyncIterImplementation()
        async_lister.side_effect = list_or_side_effect
        inner_client.list_blobs.return_value = async_lister

    class SetReturns:
        def __init__(self):
            self.download_blob_returns = set_download_return
            self.list_blobs_returns = set_list_blobs_return

    return inner_client, mockblobc, SetReturns()


@pytest.fixture()
def absc(test_config, mock_azureblob):
    return clients.azure_blobs.AzureBlobStorageClient(test_config.az_storage_url, mock.AsyncMock())


@pytest.fixture()
def async_cosmos():
    """
    This is unfortunately complex because the Async Cosmos Client uses
    an Async context manager which returns a client with _sync_ methods.

    Ultimately, we want to make it easy for a test function to mock out
    what the container client returns, but to do that, we have to mock:

    - CosmosClient (with a context manager)
    - Database Client
    - Container Client

    The last one is the one that we really want to make available to callers.

    If you get confused (and it's unfortunately easy to be confused here),
    you should litter `print("Container Client", id(container_mock))` all over
    so you can *pin down* _which_ mock thing you are looking at.
    """

    # the parent client
    cosmos_client_mock = mock.MagicMock(az_cosmos_client.CosmosClient)
    cosmos_client_mock.return_value = cosmos_client_mock

    # the database client (in the middle)
    cosmos_db_mock = mock.MagicMock(az_cosmos_client.DatabaseProxy)
    cosmos_client_mock.get_database_client.return_value = cosmos_db_mock

    # the important one where our queries will happen
    container_mock = mock.AsyncMock(az_cosmos_client.ContainerProxy)
    # the thing that will *give us back* the above
    cosmos_db_mock.get_container_client.return_value = container_mock

    return cosmos_client_mock, container_mock


@pytest.fixture(autouse=True)
def cosmos_client_mock(monkeypatch, async_cosmos):
    """Mock out Azure Async Cosmos client"""
    cosmos_client_mock, _ = async_cosmos
    monkeypatch.setattr(az_cosmos_client, "CosmosClient", cosmos_client_mock)
    monkeypatch.setattr(clients.cosmos, "CosmosClient", cosmos_client_mock)
    monkeypatch.setattr(clients.cosmos.ManagedCosmos, "ready", mock.AsyncMock())

    return cosmos_client_mock


@pytest.fixture()
def cosmos_queryable(async_cosmos):
    """Make it possible to query a specific result back from the Cosmos mock.

    Example:
        import itertools

        _, set_return = cosmos_upsertable
        # return a thing ONE TIME (remember: this is an async iterator)
        set_return("hello")

        # or repeatedly return the same thing
        set_return(None, side_effect=itertools.repeat("hello"))

    """
    _, container_mock = async_cosmos

    def set_return(return_value, side_effect=None):
        async_iter_thing = AsyncIterImplementation()
        async_iter_thing.return_value = return_value
        container_mock.query_items.return_value = async_iter_thing
        if side_effect is not None:
            async_iter_thing.side_effect = side_effect

    yield container_mock, set_return


@pytest.fixture()
def cosmos_insertable(async_cosmos):
    """Patch `create_item` on container_mock.

    Note: this is a lot simpler than returning what create_item returns.
    """
    _, container_mock = async_cosmos

    def set_return(return_value, side_effect=None):
        container_mock.create_item.return_value = return_value
        container_mock.create_item.side_effect = side_effect

    yield container_mock, set_return


@pytest.fixture()
def cosmos_updatable(async_cosmos):
    """Patch `replace_item` on container_mock.

    Note: this is a lot simpler than returning what replace_item returns.
    """
    _, container_mock = async_cosmos

    def set_return(return_value, side_effect=None):
        container_mock.replace_item.return_value = return_value
        container_mock.replace_item.side_effect = side_effect

    yield container_mock, set_return


@pytest.fixture()
def cosmos_deletable(async_cosmos):
    """Patch `delete_item` on container_mock.

    Note: this is a lot simpler than returning what delete_item returns.
    """
    _, container_mock = async_cosmos

    def set_return(return_value, side_effect=None):
        container_mock.delete_item.return_value = return_value
        container_mock.delete_item.side_effect = side_effect

    yield container_mock, set_return


@pytest.fixture()
def cosmos_readable(async_cosmos):
    """Patch `read_item` on container_mock.

    Note: this is a lot simpler than returning what read_item returns.
    """
    _, container_mock = async_cosmos

    def set_return(return_value, side_effect=None):
        container_mock.read_item.return_value = return_value
        container_mock.read_item.side_effect = side_effect

    yield container_mock, set_return


@pytest.fixture()
def cosmos_patchable(async_cosmos):
    """Patch `patch_item` on container_mock.

    Note: this is a lot simpler than returning what read_item returns.
    """
    _, container_mock = async_cosmos

    def set_return(return_value, side_effect=None):
        container_mock.patch_item.return_value = return_value
        container_mock.patch_item.side_effect = side_effect

    yield container_mock, set_return


@pytest.fixture()
def cosmos_upsertable(async_cosmos):
    """Patch `patch_item` on container_mock.

    Note: this is a lot simpler than returning what read_item returns.
    """
    _, container_mock = async_cosmos

    def set_return(return_value, side_effect=None):
        container_mock.upsert_item.return_value = return_value
        container_mock.upsert_item.side_effect = side_effect

    yield container_mock, set_return


@pytest.fixture(autouse=True)
def mockehub(monkeypatch):  # type: ignore
    """Mock out Azure Blob Service client"""
    mockev = mock.MagicMock(spec=EventHubProducerClient)
    mockev.create_batch = mock.AsyncMock(return_value=mockev)
    mockev.send_batch = mock.AsyncMock()
    mockev.add = mock.Mock()

    def get_client(*args, **kwargs):
        return mockev

    monkeypatch.setattr(clients.eventhub.Eventhub, "get_client", get_client)
    return mockev


@pytest.fixture(autouse=True)
def mockegrid(monkeypatch):  # type: ignore
    """Mock out Azure Eventgrid client"""
    mockeg = mock.MagicMock(spec=EventGridPublisherClient)
    mockeg.return_value = mockeg

    async_mockeg = mock.MagicMock(spec=AsyncEventGridPublisherClient)
    async_mockeg.return_value = make_async_ctx_mgr(async_mockeg)

    monkeypatch.setattr(clients.eventgrid, "EventGridPublisherClient", mockeg)
    monkeypatch.setattr(clients.eventgrid, "AsyncEventGridPublisherClient", async_mockeg)
    return mockeg, async_mockeg


@pytest.fixture(autouse=True)
def mockservicebus(monkeysession):  # type: ignore
    """Mock out Azure Blob Service client"""
    mocksb = mock.MagicMock(ServiceBusClient)

    # Receiver client
    receiver_client = mock.AsyncMock()
    ctx_receiver = make_async_ctx_mgr(receiver_client)
    mocksb.get_queue_receiver = mock.PropertyMock(return_value=ctx_receiver)
    # Sender client reuse mocksb
    sender_client = mock.AsyncMock()
    ctx_sender = make_async_ctx_mgr(sender_client)
    mocksb.get_queue_sender = mock.PropertyMock(return_value=ctx_sender)

    def get_client(*args, **kwargs):
        # Wrap it up so it can be used as a context manager
        return make_async_ctx_mgr(mocksb)

    monkeysession.setattr(
        clients.service_bus,
        "ServiceBusClient",
        get_client,
    )
    mocksb._receiver = receiver_client
    mocksb._sender = sender_client
    sender_client.schedule_messages = mock.AsyncMock()

    return mocksb


@pytest.fixture()
def sbus(mockservicebus):
    return clients.service_bus.AzureServiceBus(
        "https://sbus.example.com",
        "fake-queue-name",
        mock.AsyncMock(),  # fake credential
    )


@pytest.fixture()
def managed_sbus(mockservicebus):
    return clients.service_bus.ManagedAzureServiceBusSender(
        "https://sbus.example.com",
        "fake-queue-name",
        mock.AsyncMock(),  # fake credential
    )
