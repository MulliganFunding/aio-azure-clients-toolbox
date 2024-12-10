from unittest import mock

import pytest
from aio_azure_clients_toolbox.clients import eventgrid


@pytest.fixture()
def topic():
    return eventgrid.EventGridTopicConfig("test", "some-url")


@pytest.fixture()
def eg_config(topic):
    return eventgrid.EventGridConfig(topic)


def test_eg_config(eg_config, topic):
    assert eg_config.topics() == ["test"]

    assert eg_config.config("test") == topic


def test_url(eg_config):
    assert eg_config.url("test") == "some-url"


@pytest.fixture()
def sync_client(eg_config):
    return eventgrid.EventGridClient(eg_config, credential=mock.Mock())


@pytest.fixture()
def async_client(eg_config):
    return eventgrid.EventGridClient(eg_config, async_credential=mock.AsyncMock())


def test_emit_event(mockegrid, sync_client):
    mock_sync, _ = mockegrid
    sync_client.emit_event("test", "event", "subect", {"data": "true"})
    assert sync_client.get_client("test")
    assert mock_sync.method_calls
    assert mock_sync.method_calls[0][0] == "send"


async def test_async_emit_event(mockegrid, async_client):
    _, mock_async = mockegrid
    await async_client.async_emit_event("test", "event", "subect", {"data": "true"})
    assert async_client.get_async_client("test")
    assert mock_async.send.called, "The send method was not called."
