from unittest import mock

import pytest
from aio_azure_clients_toolbox.clients import eventhub


@pytest.fixture()
def ehub(mockehub):
    return eventhub.Eventhub(
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


async def test_evhub_send_event_batch(ehub):
    await ehub.send_events_batch(["test1", "test2"])
    assert len(ehub._client.method_calls) == 4
