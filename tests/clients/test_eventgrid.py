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


def test_no_credential_raises():
    config = eventgrid.EventGridConfig(eventgrid.EventGridTopicConfig("t", "url"))
    with pytest.raises(ValueError, match="Must provide credential or async_credential"):
        eventgrid.EventGridClient(config)


def test_both_credentials_raises():
    config = eventgrid.EventGridConfig(eventgrid.EventGridTopicConfig("t", "url"))
    with pytest.raises(ValueError, match="Must provide only ONE"):
        eventgrid.EventGridClient(config, credential=mock.Mock(), async_credential=mock.AsyncMock())


def test_init_clients_without_credential():
    config = eventgrid.EventGridConfig(eventgrid.EventGridTopicConfig("t", "url"))
    client = eventgrid.EventGridClient(config, async_credential=mock.AsyncMock())
    # _init_clients guard
    with pytest.raises(ValueError, match="credential must be provided to init sync clients"):
        client._init_clients()


def test_init_async_clients_without_async_credential():
    config = eventgrid.EventGridConfig(eventgrid.EventGridTopicConfig("t", "url"))
    client = eventgrid.EventGridClient(config, credential=mock.Mock())
    # _init_async_clients guard
    with pytest.raises(ValueError, match="async_credential must be provided to init async clients"):
        client._init_async_clients()


def test_is_sync(sync_client, async_client):
    assert sync_client.is_sync() is True
    assert async_client.is_sync() is False
