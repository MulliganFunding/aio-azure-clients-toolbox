from unittest import mock

import pytest
from aio_azure_clients_toolbox.clients import eventhub
from azure.eventhub import EventData, EventDataBatch
from azure.eventhub.exceptions import AuthenticationError, ClientClosedError, ConnectError

# Three calls to send a ready message
READY_MESSAGE_METHOD_CALLS = ["create_batch", "add", "send"]
READY_MESSAGE_CALL_COUNT = len(READY_MESSAGE_METHOD_CALLS)


@pytest.fixture()
def ehub(mockehub):
    return eventhub.Eventhub(
        "namespace_url.example.net",
        "name",
        mock.AsyncMock(),  # credential
    )


@pytest.fixture()
def managed_ehub(mockehub):
    return eventhub.ManagedAzureEventhubProducer(
        "namespace_url.example.net",
        "name",
        mock.AsyncMock(),  # credential
    )


def test_get_client(ehub, mockehub):
    assert ehub.get_client() == mockehub
    ehub._client = None
    assert ehub.client == mockehub
    assert ehub._client is not None


async def test_close(ehub):
    # set up
    _ = ehub.client
    await ehub.close()
    assert ehub._client is None
    # Should be fine to call multiple times
    await ehub.close()


async def test_evhub_send_event(ehub):
    await ehub.send_event("test")
    assert len(ehub._client.method_calls) == 3


async def test_evhub_send_event_data(ehub):
    data = EventData(body=b"test")
    await ehub.send_event_data(data)
    assert len(ehub._client.method_calls) == 3


async def test_evhub_send_event_batch(ehub):
    await ehub.send_events_batch(["test1", "test2"])
    assert len(ehub._client.method_calls) == 4


async def test_evhub_send_events_data_batch(ehub):
    batch = EventDataBatch()
    batch.add(EventData(body=b"test1"))
    batch.add(EventData(body=b"test2"))

    await ehub.send_events_data_batch(batch)
    assert len(ehub._client.method_calls) == 1


# # # # # # # # # # # # # # # # # #
# ---**--> Managed Client <--**---
# # # # # # # # # # # # # # # # # #


async def test_managed_get_create(managed_ehub, mockehub):
    assert await managed_ehub.create() == mockehub


async def test_managed_close(managed_ehub):
    # set up
    async with managed_ehub.pool.get() as _conn1:
        async with managed_ehub.pool.get() as _conn2:
            pass
        assert managed_ehub.pool.ready_connection_count == 2
    await managed_ehub.close()
    assert managed_ehub.pool.ready_connection_count == 0


def get_mock_connection_from_pool(pool):
    # This is expected to be a mock thing buried in here
    return pool._pool[0]._connection


@pytest.fixture(params=[False, True])
def mockehub_throwing(request, mockehub):
    if request.param:
        # We need the *first* (readiness) call to succeed, and the second to fail
        mockehub.send_batch.side_effect = [None, ClientClosedError("test")]
    return (mockehub, request.param)


async def test_ready_auth_failure(mockehub, managed_ehub):
    mockehub.send_batch.side_effect = AuthenticationError("test")
    assert not await managed_ehub.ready(mockehub)
    assert mockehub.send_batch.call_count == 1


async def test_ready_connect_failure(mockehub, managed_ehub):
    mockehub.send_batch.side_effect = ConnectError("test")
    assert not await managed_ehub.ready(mockehub)
    assert mockehub.send_batch.call_count == 2


async def test_managed_evhub_send_event(mockehub_throwing, managed_ehub):
    _mockehub, should_throw = mockehub_throwing
    expect_call_count = READY_MESSAGE_CALL_COUNT + 3
    if should_throw:
        with pytest.raises(ClientClosedError):
            await managed_ehub.send_event("test")
        # Connection should be closed
        assert managed_ehub.pool.ready_connection_count == 0
        expect_call_count += 1  # for the close
    else:
        await managed_ehub.send_event("test")
        assert (
            len(get_mock_connection_from_pool(managed_ehub.pool).method_calls)
            == expect_call_count
        )


async def test_managed_evhub_send_event_data(mockehub_throwing, managed_ehub):
    _mockehub, should_throw = mockehub_throwing
    data = EventData(body=b"test")
    expect_call_count = READY_MESSAGE_CALL_COUNT + 3
    if should_throw:
        with pytest.raises(ClientClosedError):
            await managed_ehub.send_event_data(data)
        # Connection should be closed
        assert managed_ehub.pool.ready_connection_count == 0
        expect_call_count += 1  # for the close
    else:
        await managed_ehub.send_event_data(data)
        assert (
            len(get_mock_connection_from_pool(managed_ehub.pool).method_calls)
            == expect_call_count
        )


async def test_managed_evhub_send_event_batch(mockehub_throwing, managed_ehub):
    _mockehub, should_throw = mockehub_throwing
    expect_call_count = READY_MESSAGE_CALL_COUNT + 4

    if should_throw:
        with pytest.raises(ClientClosedError):
            await managed_ehub.send_events_batch(["test1", "test2"])
        assert managed_ehub.pool.ready_connection_count == 0
        expect_call_count += 1  # for the close

    else:
        await managed_ehub.send_events_batch(["test1", "test2"])
        assert (
            len(get_mock_connection_from_pool(managed_ehub.pool).method_calls)
            == expect_call_count
        )


async def test_managed_evhub_send_events_data_batch(mockehub_throwing, managed_ehub):
    batch = EventDataBatch()
    batch.add(EventData(body=b"test1"))
    batch.add(EventData(body=b"test2"))
    _mockehub, should_throw = mockehub_throwing
    expect_call_count = READY_MESSAGE_CALL_COUNT + 1
    if should_throw:
        with pytest.raises(ClientClosedError):
            await managed_ehub.send_events_data_batch(batch)
        assert managed_ehub.pool.ready_connection_count == 0
        expect_call_count += 1 # for the close
    else:
        await managed_ehub.send_events_data_batch(batch)
        assert (
            len(get_mock_connection_from_pool(managed_ehub.pool).method_calls)
            == expect_call_count
        )
