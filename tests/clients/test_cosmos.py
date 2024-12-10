from unittest import mock

import pytest
from aio_azure_clients_toolbox.clients import cosmos


@pytest.fixture()
def cos_client():
    return cosmos.Cosmos(
        "https://documents.example.com",
        "testing-db",
        "testing-container",
        mock.Mock(),
    )


async def test_query(cos_client, cosmos_readable):
    qclient, set_return = cosmos_readable
    expected = {"a": "b"}
    set_return(expected)

    async with cos_client.get_container_client() as client:
        result = await client.read_item(item="a", partition_key="a")
        assert result == expected


async def test_close(cos_client):
    # sanity check
    assert cos_client.connection_manager.is_container_closed
    assert cos_client.connection_manager.should_recycle_container
    # These shouldn't fail
    await cos_client.connection_manager.get_container_client()
    assert not cos_client.connection_manager.should_recycle_container

    # Also shouldn't fail (if mocks are set up wrong this will fail)
    await cos_client.close()
    await cos_client.connection_manager.recycle_container()
