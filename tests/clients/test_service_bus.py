import pytest
from azure.servicebus.exceptions import (
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
    assert sbus.get_sender() is sender


async def test_close(sbus):
    # Make sure these things are bootstrapped
    sbus.get_receiver()
    sbus.get_sender()

    await sbus.close()
    assert sbus._receiver_client is None
    assert sbus._sender_client is None
    assert sbus._client is None


async def test_send_message(sbus, mockservicebus):
    await sbus.send_message("hey")
    assert mockservicebus._sender.method_calls


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
    assert managed_sbus.get_sender() is sender


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
