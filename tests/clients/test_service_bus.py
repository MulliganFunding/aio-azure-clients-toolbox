import asyncio
from unittest import mock

import pytest
from aio_azure_clients_toolbox.clients import service_bus
from azure.servicebus.exceptions import (
    OperationTimeoutError,
    ServiceBusAuthenticationError,
    ServiceBusConnectionError,
)


def test_validate_settings(sbus):
    assert sbus._validate_access_settings() is None
    with pytest.raises(ValueError):
        sbus.queue_name = ""
        sbus._validate_access_settings()


async def test_get_receiver(sbus, mockservicebus):
    receiver = sbus.get_receiver()
    await receiver.bla()
    assert mockservicebus._receiver.method_calls
    assert sbus.get_receiver() is receiver


async def test_get_sender(sbus, mockservicebus):
    sender = sbus.get_sender()
    await sender.bla()
    assert mockservicebus._sender.method_calls
    sender2 = sbus.get_sender()
    assert sender2.attribute is sender.attribute


async def test_close(sbus):
    # Make sure these things are bootstrapped
    sbus.get_receiver()
    sbus.get_sender()

    await sbus.close()
    assert sbus._receiver_client is None
    assert sbus._sender_client is None
    assert sbus._receiver_credential is None


async def test_send_message(sbus, mockservicebus):
    await sbus.send_message("hey")
    assert mockservicebus._sender.method_calls


async def test_send_message_with_unique_msg_id(sbus, mockservicebus):
    unique_msg_id = "unique-msg-123"
    await sbus.send_message("hey", unique_msg_id=unique_msg_id)

    scheduled_message = mockservicebus._sender.schedule_messages.call_args.args[0]
    assert scheduled_message.message_id == unique_msg_id


# # # # # # # # # # # # # # # # # #
# ---**--> Managed Client <--**---
# # # # # # # # # # # # # # # # # #
async def test_managed_get_receiver(managed_sbus, mockservicebus):
    receiver = managed_sbus.get_receiver()
    await receiver.bla()
    assert mockservicebus._receiver.method_calls
    assert managed_sbus.get_receiver() is receiver


async def test_managed_get_sender(managed_sbus, mockservicebus):
    sender = managed_sbus.get_sender()
    await sender.bla()
    assert mockservicebus._sender.method_calls
    sender2 = managed_sbus.get_sender()
    assert sender2.attribute is sender.attribute


async def test_managed_close(managed_sbus):
    # Make sure these things are bootstrapped
    async with managed_sbus.pool.get() as _conn1:
        async with managed_sbus.pool.get() as _conn2:
            pass
        assert managed_sbus.pool.ready_connection_count == 2
    await managed_sbus.close()
    assert managed_sbus.pool.ready_connection_count == 0


def get_mock_connection_from_pool(pool):
    # This is expected to be a mock thing buried in here
    return pool._pool[0]._connection


@pytest.fixture(params=[False, True])
def managed_sbus_throwing(request, mockservicebus):
    if request.param:
        # We need the *first* (readiness) call to succeed, and the second to fail
        mockservicebus._sender.schedule_messages.side_effect = [None, ServiceBusConnectionError()]
    return (mockservicebus, request.param)


async def test_ready_auth_failure(mockservicebus, managed_sbus):
    mockservicebus._sender.schedule_messages.side_effect = ServiceBusAuthenticationError()
    with pytest.raises(ServiceBusAuthenticationError):
        await managed_sbus.ready(await managed_sbus.create())

    assert mockservicebus._sender.schedule_messages.call_count == 1


async def test_ready_connect_failure(mockservicebus, managed_sbus):
    mockservicebus._sender.schedule_messages.side_effect = ServiceBusConnectionError()
    assert not await managed_sbus.ready(await managed_sbus.create())
    assert mockservicebus._sender.schedule_messages.call_count == 2


async def test_managed_sbus_send_message(managed_sbus_throwing, managed_sbus):
    mockservicebus, should_throw = managed_sbus_throwing
    expect_call_count = 2
    if should_throw:
        with pytest.raises(ServiceBusConnectionError):
            await managed_sbus.send_message("test")
        # Connection should be closed
        assert managed_sbus.pool.ready_connection_count == 0
        expect_call_count += 1  # for the close
    else:
        await managed_sbus.send_message("test")
        assert (
            len(get_mock_connection_from_pool(managed_sbus.pool).method_calls)
            == expect_call_count
        )


async def test_managed_send_message(managed_sbus, mockservicebus):
    await managed_sbus.send_message("hey")
    assert mockservicebus._sender.method_calls


async def test_managed_send_message_returns_sequence_numbers_and_passes_timeout(
    managed_sbus, mockservicebus
):
    # First call is the readiness check
    mockservicebus._sender.schedule_messages.side_effect = [None, [42]]
    assert await managed_sbus.send_message("hey") == [42]

    send_call = mockservicebus._sender.schedule_messages.call_args
    assert send_call.kwargs["timeout"] == service_bus.SERVICE_BUS_SEND_TIMEOUT_SECONDS


async def test_managed_send_message_timeout_does_not_close_connection(managed_sbus, mockservicebus):
    mockservicebus._sender.schedule_messages.side_effect = [None, OperationTimeoutError()]
    with pytest.raises(OperationTimeoutError):
        await managed_sbus.send_message("hey")

    mockservicebus._sender.close.assert_not_awaited()
    assert managed_sbus.pool.ready_connection_count == 1
    assert mockservicebus._sender.schedule_messages.call_count == 2


async def test_managed_send_message_timeout_retries_through_pool(mockservicebus):
    sbus = service_bus.ManagedAzureServiceBusSender(
        "https://sbus.example.com",
        "fake-queue-name",
        lambda: mock.AsyncMock(),
        send_timeout_seconds=5,
        send_attempts=2,
    )
    # ready, timed-out send, successful send
    mockservicebus._sender.schedule_messages.side_effect = [
        None,
        OperationTimeoutError(),
        [7],
    ]
    assert await sbus.send_message("hey", unique_msg_id="task-1") == [7]

    calls = mockservicebus._sender.schedule_messages.call_args_list
    assert len(calls) == 3
    assert calls[1].args[0] is calls[2].args[0]
    assert calls[2].args[0].message_id == "task-1"
    assert all(call.kwargs["timeout"] == 5 for call in calls)
    mockservicebus._sender.close.assert_not_awaited()


async def test_managed_send_message_timeout_exhausts_attempts(mockservicebus):
    sbus = service_bus.ManagedAzureServiceBusSender(
        "https://sbus.example.com",
        "fake-queue-name",
        lambda: mock.AsyncMock(),
        send_attempts=2,
    )
    mockservicebus._sender.schedule_messages.side_effect = [
        None,
        OperationTimeoutError(),
        OperationTimeoutError(),
    ]
    with pytest.raises(OperationTimeoutError):
        await sbus.send_message("hey")

    assert mockservicebus._sender.schedule_messages.call_count == 3
    mockservicebus._sender.close.assert_not_awaited()


async def test_managed_send_message_timeout_does_not_interrupt_concurrent_send(mockservicebus):
    """One send times out while another is in flight on the same connection."""
    # A single pool slot forces both sends onto the same connection
    sbus = service_bus.ManagedAzureServiceBusSender(
        "https://sbus.example.com",
        "fake-queue-name",
        lambda: mock.AsyncMock(),
        max_size=1,
    )
    release_timed_out = asyncio.Event()
    release_concurrent = asyncio.Event()

    async def schedule_messages(message, *args, **kwargs):
        body = str(message)
        if body == "times-out":
            await release_timed_out.wait()
            raise OperationTimeoutError()
        if body == "concurrent":
            await release_concurrent.wait()
            return [9]
        return None  # readiness check

    mockservicebus._sender.schedule_messages.side_effect = schedule_messages

    timed_out = asyncio.create_task(sbus.send_message("times-out"))
    concurrent = asyncio.create_task(sbus.send_message("concurrent"))
    # readiness check + both sends
    while mockservicebus._sender.schedule_messages.call_count < 3:
        await asyncio.sleep(0)
    assert sbus.pool._pool[0].current_client_count == 2

    release_timed_out.set()
    with pytest.raises(OperationTimeoutError):
        await timed_out

    release_concurrent.set()
    assert await concurrent == [9]
    mockservicebus._sender.close.assert_not_awaited()


@pytest.mark.parametrize(
    "kwargs",
    [{"send_timeout_seconds": 0}, {"send_attempts": 0}],
)
def test_managed_sbus_bad_send_settings(kwargs):
    with pytest.raises(ValueError):
        service_bus.ManagedAzureServiceBusSender(
            "https://sbus.example.com",
            "queue",
            credential_factory=lambda: mock.AsyncMock(),
            **kwargs,
        )


async def test_managed_send_message_with_unique_msg_id(managed_sbus, mockservicebus):
    unique_msg_id = "managed-unique-msg-123"
    await managed_sbus.send_message("hey", unique_msg_id=unique_msg_id)

    scheduled_message = mockservicebus._sender.schedule_messages.call_args.args[0]
    assert scheduled_message.message_id == unique_msg_id


# # # # # # # # # # # # # # # # # #
# ---**--> Validation & edge cases <--**---
# # # # # # # # # # # # # # # # # #
def test_basic_sbus_no_credential_or_connection_string():
    with pytest.raises(ValueError, match="credential_factory must be a callable"):
        service_bus.AzureServiceBus(
            "https://sbus.example.com",
            "queue",
        )


def test_managed_sbus_no_credential_or_connection_string():
    with pytest.raises(ValueError, match="credential_factory must be a callable"):
        service_bus.ManagedAzureServiceBusSender(
            "https://sbus.example.com",
            "queue",
        )


def test_managed_sbus_bad_ready_message():
    with pytest.raises(ValueError, match="ready_message must be a string or bytes"):
        service_bus.ManagedAzureServiceBusSender(
            "https://sbus.example.com",
            "queue",
            credential_factory=lambda: mock.AsyncMock(),
            ready_message=12345,  # noqa: B033
        )


async def test_basic_sbus_connection_string_receiver(monkeypatch, mockservicebus):
    mock_sbc = mock.MagicMock()
    mock_sbc.get_queue_receiver = mock.PropertyMock(return_value=mock.AsyncMock())
    mock_sbc.from_connection_string = mock.Mock(return_value=mock_sbc)
    monkeypatch.setattr(service_bus, "ServiceBusClient", mock_sbc)

    sbus = service_bus.AzureServiceBus(
        "https://sbus.example.com",
        "queue",
        connection_string="Endpoint=sb://fake",
    )
    receiver = sbus.get_receiver()
    assert receiver is not None
    mock_sbc.from_connection_string.assert_called_once()


async def test_basic_sbus_connection_string_sender(monkeypatch, mockservicebus):
    mock_sbc = mock.MagicMock()
    mock_sbc.get_queue_sender = mock.PropertyMock(return_value=mock.AsyncMock())
    mock_sbc.from_connection_string = mock.Mock(return_value=mock_sbc)
    monkeypatch.setattr(service_bus, "ServiceBusClient", mock_sbc)

    sbus = service_bus.AzureServiceBus(
        "https://sbus.example.com",
        "queue",
        connection_string="Endpoint=sb://fake",
    )
    sender = sbus.get_sender()
    assert sender is not None
    mock_sbc.from_connection_string.assert_called_once()


async def test_managed_close_with_receiver(managed_sbus, mockservicebus):
    """Test close() when a receiver has been created"""
    _ = managed_sbus.get_receiver()
    await managed_sbus.close()
    assert managed_sbus._receiver_client is None
