from unittest import mock

import pytest
from aio_azure_clients_toolbox.clients import cosmos

# # # # # # # # # # # # # # # # # #
# ---**--> Basic Cosmos Client <--**---
# # # # # # # # # # # # # # # # # #


@pytest.fixture()
def cos_client():
    return cosmos.Cosmos(
        "https://documents.example.com",
        "testing-db",
        "testing-container",
        lambda: mock.AsyncMock(),
    )


def test_get_client(cos_client):
    # Initial state check
    assert cos_client.connection_manager.is_container_closed
    assert cos_client.connection_manager.should_recycle_container


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


async def test_cosmos_read_item(cos_client, cosmos_readable):
    qclient, set_return = cosmos_readable
    expected = {"a": "b"}
    set_return(expected)

    async with cos_client.get_container_client() as client:
        result = await client.read_item(item="a", partition_key="a")
        assert result == expected


async def test_cosmos_query_items(cos_client, cosmos_queryable):
    qclient, set_return = cosmos_queryable
    expected = [{"id": "1", "name": "test1"}, {"id": "2", "name": "test2"}]
    set_return(None, side_effect=expected)

    items = []
    async with cos_client.get_container_client() as client:
        async for item in client.query_items("SELECT * FROM c"):
            items.append(item)

    assert items == expected


async def test_cosmos_create_item(cos_client, cosmos_insertable):
    qclient, set_return = cosmos_insertable
    test_item = {"id": "test", "name": "test item"}
    set_return(test_item)

    async with cos_client.get_container_client() as client:
        result = await client.create_item(test_item)
        assert result == test_item


async def test_cosmos_replace_item(cos_client, cosmos_updatable):
    qclient, set_return = cosmos_updatable
    test_item = {"id": "test", "name": "updated item"}
    set_return(test_item)

    async with cos_client.get_container_client() as client:
        result = await client.replace_item(item="test", body=test_item)
        assert result == test_item


async def test_cosmos_delete_item(cos_client, cosmos_deletable):
    qclient, set_return = cosmos_deletable
    set_return(None)

    async with cos_client.get_container_client() as client:
        await client.delete_item(item="test", partition_key="test")
        # Just ensure no exception is raised


async def test_cosmos_patch_item(cos_client, cosmos_patchable):
    qclient, set_return = cosmos_patchable
    patched_item = {"id": "test", "name": "patched item"}
    set_return(patched_item)

    patch_ops = [{"op": "replace", "path": "/name", "value": "patched item"}]
    async with cos_client.get_container_client() as client:
        result = await client.patch_item(
            item="test", partition_key="test", patch_operations=patch_ops
        )
        assert result == patched_item


async def test_cosmos_upsert_item(cos_client, cosmos_upsertable):
    qclient, set_return = cosmos_upsertable
    test_item = {"id": "test", "name": "upserted item"}
    set_return(test_item)

    async with cos_client.get_container_client() as client:
        result = await client.upsert_item(test_item)
        assert result == test_item


# # # # # # # # # # # # # # # # # #
# ---**--> Simple Cosmos Client <--**---
# # # # # # # # # # # # # # # # # #


@pytest.fixture()
def simple_cos_client():
    return cosmos.SimpleCosmos(
        "https://documents.example.com",
        "testing-db",
        "testing-container",
        mock.AsyncMock(),
    )


async def test_simple_cosmos_get_container_client(simple_cos_client):
    client = await simple_cos_client.get_container_client()
    assert client is simple_cos_client
    assert simple_cos_client._client is not None
    assert simple_cos_client._db is not None
    assert simple_cos_client._container is not None


async def test_simple_cosmos_close(simple_cos_client):
    # First create the client
    await simple_cos_client.get_container_client()
    assert simple_cos_client._client is not None

    # Now close it
    await simple_cos_client.close()
    assert simple_cos_client._client is None
    assert simple_cos_client._db is None
    assert simple_cos_client._container is None


async def test_simple_cosmos_getattr_without_container(simple_cos_client):
    # Should raise AttributeError when no container is created
    with pytest.raises(AttributeError, match="Container client not constructed"):
        _ = simple_cos_client.read_item


async def test_simple_cosmos_getattr_with_container(simple_cos_client, cosmos_readable):
    qclient, set_return = cosmos_readable
    expected = {"a": "b"}
    set_return(expected)

    # Create the container client first
    await simple_cos_client.get_container_client()

    # Now we should be able to access methods
    result = await simple_cos_client.read_item(item="a", partition_key="a")
    assert result == expected


# # # # # # # # # # # # # # # # # #
# ---**--> Managed Cosmos Client <--**---
# # # # # # # # # # # # # # # # # #


@pytest.fixture()
def managed_cos_client():
    return cosmos.ManagedCosmos(
        "https://documents.example.com",
        "testing-db",
        "testing-container",
        lambda: mock.AsyncMock(),
    )


async def test_managed_cosmos_create(managed_cos_client):
    client = await managed_cos_client.create()
    assert isinstance(client, cosmos.SimpleCosmos)
    assert client._client is not None


async def test_managed_cosmos_close(managed_cos_client):
    # Set up some connections in the pool
    async with managed_cos_client.pool.get() as _conn1:
        async with managed_cos_client.pool.get() as _conn2:
            pass
        assert managed_cos_client.pool.ready_connection_count == 2

    await managed_cos_client.close()
    assert managed_cos_client.pool.ready_connection_count == 0


def get_mock_connection_from_pool(pool):
    # Helper to get the mock connection from the pool
    return pool._pool[0]._connection


async def test_managed_cosmos_get_container_client(managed_cos_client, cosmos_readable):
    qclient, set_return = cosmos_readable
    expected = {"id": "1", "data": "test"}
    set_return(expected)

    async with managed_cos_client.get_container_client() as client:
        result = await client.read_item(item="1", partition_key="1")
        assert result == expected


async def test_managed_cosmos_runtime_error_handling(
    managed_cos_client, cosmos_readable
):
    qclient, set_return = cosmos_readable
    set_return(None, side_effect=RuntimeError("Connection failed"))

    with pytest.raises(RuntimeError, match="Connection failed"):
        async with managed_cos_client.get_container_client() as client:
            await client.read_item(item="1", partition_key="1")


# # # # # # # # # # # # # # # # # #
# ---**--> Utility Classes <--**---
# # # # # # # # # # # # # # # # # #


def test_patch_op_enum():
    # Test all PatchOp values
    assert cosmos.PatchOp.Add.value == "add"
    assert cosmos.PatchOp.Remove.value == "remove"
    assert cosmos.PatchOp.Replace.value == "replace"
    assert cosmos.PatchOp.Set.value == "set"
    assert cosmos.PatchOp.Incr.value == "incr"
    assert cosmos.PatchOp.Move.value == "move"


def test_patch_op_as_op():
    # Test regular operations
    add_op = cosmos.PatchOp.Add.as_op("/path", "value")
    assert add_op == {"op": "add", "path": "/path", "value": "value"}

    replace_op = cosmos.PatchOp.Replace.as_op("/name", "new_name")
    assert replace_op == {"op": "replace", "path": "/name", "value": "new_name"}

    # Test move operation (special case)
    move_op = cosmos.PatchOp.Move.as_op("/from_path", "/to_path")
    assert move_op == {"op": "move", "from": "/from_path", "path": "/to_path"}


def test_operation_dataclass():
    # Test Operation dataclass
    op = cosmos.Operation(cosmos.PatchOp.Add, "/test", "test_value")
    assert op.op == cosmos.PatchOp.Add
    assert op.path == "/test"
    assert op.value == "test_value"

    # Test as_op method
    op_dict = op.as_op()
    assert op_dict == {"op": "add", "path": "/test", "value": "test_value"}


def test_operation_move_dataclass():
    # Test Operation dataclass with Move operation
    op = cosmos.Operation(cosmos.PatchOp.Move, "/from", "/to")
    op_dict = op.as_op()
    assert op_dict == {"op": "move", "from": "/from", "path": "/to"}
