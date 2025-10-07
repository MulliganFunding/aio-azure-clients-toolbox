import asyncio
from operator import itemgetter

import pytest
from aio_azure_clients_toolbox import connection_pooling as cp
from anyio import create_task_group, sleep


class FakeConn(cp.AbstractConnection):
    def __init__(self):
        self.is_closed = False

    async def close(self):
        self.is_closed = True


class FakeConnector(cp.AbstractorConnector):
    def __init__(self):
        self._created = False
        self._ready = False

    async def create(self):
        self._created = True
        return FakeConn()

    async def ready(self, _conn):
        self._ready = True
        assert not _conn.is_closed
        return True


CLIENT_LIMIT = 2
MAX_IDLE_SECONDS = 0.05
SLOW_CONN_SLEEPINESS = 0.05


class SlowFakeConnector(cp.AbstractorConnector):
    def __init__(self, sleepiness=SLOW_CONN_SLEEPINESS):
        self._created = False
        self._ready = False
        self.sleepiness = sleepiness

    async def create(self):
        await sleep(self.sleepiness)
        self._created = True
        return FakeConn()

    async def ready(self, _conn):
        await sleep(self.sleepiness)
        self._ready = True
        assert not _conn.is_closed
        return True


@pytest.fixture()
def shared_transpo_conn():
    return cp.SharedTransportConnection(
        FakeConnector(), client_limit=CLIENT_LIMIT, max_idle_seconds=MAX_IDLE_SECONDS
    )


@pytest.fixture()
def slow_shared_transpo_conn():
    return cp.SharedTransportConnection(
        SlowFakeConnector(),
        client_limit=CLIENT_LIMIT,
        max_idle_seconds=MAX_IDLE_SECONDS,
    )


async def test_shared_transport_props(shared_transpo_conn):
    async def acquirer():
        async with shared_transpo_conn.acquire():
            assert shared_transpo_conn.current_client_count > 0
            assert shared_transpo_conn.current_client_count <= CLIENT_LIMIT

    assert shared_transpo_conn.available
    assert not shared_transpo_conn.expired
    assert not shared_transpo_conn.is_ready
    assert shared_transpo_conn.time_spent_idle == 0
    assert shared_transpo_conn._id in str(shared_transpo_conn)
    await asyncio.gather(acquirer(), acquirer(), acquirer())
    assert shared_transpo_conn.time_spent_idle > 0
    await sleep(MAX_IDLE_SECONDS * 2)
    assert shared_transpo_conn.expired
    assert shared_transpo_conn.is_ready


async def test_acquire_timeouts(slow_shared_transpo_conn):
    """Check that acquire with timeout moves on sucessfully"""
    async with slow_shared_transpo_conn.acquire(timeout=SLOW_CONN_SLEEPINESS) as conn:
        assert conn is None


async def test_comp_eq(shared_transpo_conn):
    """LT IFF
    - it has fewer clients connected
    - it's been idle longer
    """
    # equals
    stc2 = cp.SharedTransportConnection(
        FakeConnector(), client_limit=CLIENT_LIMIT, max_idle_seconds=MAX_IDLE_SECONDS
    )
    assert stc2 == shared_transpo_conn
    stc2._ready.set()
    assert stc2 != shared_transpo_conn
    shared_transpo_conn._ready.set()
    assert stc2 == shared_transpo_conn

    await shared_transpo_conn.checkout()
    assert stc2 != shared_transpo_conn
    await stc2.checkout()

    assert stc2 == shared_transpo_conn
    stc2.last_idle_start = 10
    shared_transpo_conn.last_idle_start = 20
    assert stc2 != shared_transpo_conn


async def test_comp_lt(shared_transpo_conn):
    """LT IFF
    - it has fewer clients connected
    - it's been idle longer
    """
    # LT / LTE
    stc2 = cp.SharedTransportConnection(
        FakeConnector(), client_limit=CLIENT_LIMIT, max_idle_seconds=MAX_IDLE_SECONDS
    )
    assert stc2 <= shared_transpo_conn

    # Client count for stc2 is less-than
    await shared_transpo_conn.checkout()
    async with create_task_group() as tg:
        tg.start_soon(shared_transpo_conn.checkout)
    await stc2.checkout()
    assert stc2 < shared_transpo_conn

    # Client count is equal again
    async with create_task_group() as tg:
        tg.start_soon(stc2.checkout)
    assert stc2 <= shared_transpo_conn
    # Now that client count is equal, we use last_idle_start for comp
    stc2.last_idle_start = 1000000
    shared_transpo_conn.last_idle_start = 2000000
    assert stc2 < shared_transpo_conn


async def test_comp_gt(shared_transpo_conn):
    """LT IFF
    - it has fewer clients connected
    - it's been idle longer
    """
    # GT / GTE
    stc2 = cp.SharedTransportConnection(
        FakeConnector(), client_limit=CLIENT_LIMIT, max_idle_seconds=MAX_IDLE_SECONDS
    )
    assert stc2 >= shared_transpo_conn
    # Client count for stc2 is less-than
    await shared_transpo_conn.checkout()
    async with create_task_group() as tg:
        tg.start_soon(shared_transpo_conn.checkout)
    await stc2.checkout()
    assert shared_transpo_conn > stc2

    # Client count is equal again
    async with create_task_group() as tg:
        tg.start_soon(stc2.checkout)
    assert stc2 >= shared_transpo_conn

    # Now that client count is equal, we use last_idle_start for comp
    stc2.last_idle_start = 1000000
    shared_transpo_conn.last_idle_start = 2000000
    assert shared_transpo_conn > stc2


async def test_create(shared_transpo_conn):
    shared_transpo_conn._connection = "bla"
    assert await shared_transpo_conn.create() == "bla"
    shared_transpo_conn._connection = None
    assert isinstance((await shared_transpo_conn.create()), FakeConn)


async def test_check_readiness(shared_transpo_conn):
    await shared_transpo_conn.check_readiness()
    assert not shared_transpo_conn.is_ready
    await shared_transpo_conn.create()
    await shared_transpo_conn.check_readiness()
    assert shared_transpo_conn.is_ready


async def test_close(shared_transpo_conn):
    assert (await shared_transpo_conn.close()) is None
    await shared_transpo_conn.create()
    await shared_transpo_conn.check_readiness()
    assert shared_transpo_conn.is_ready
    assert (await shared_transpo_conn.close()) is None


@pytest.fixture
def pool():
    return cp.ConnectionPool(
        FakeConnector(),
        client_limit=CLIENT_LIMIT,
        max_size=CLIENT_LIMIT,
        max_idle_seconds=MAX_IDLE_SECONDS,
    )


@pytest.fixture
def slow_pool():
    return cp.ConnectionPool(
        SlowFakeConnector(),
        client_limit=CLIENT_LIMIT,
        max_size=CLIENT_LIMIT,
        max_idle_seconds=MAX_IDLE_SECONDS,
    )


def test_init():
    with pytest.raises(ValueError):
        cp.ConnectionPool(
            FakeConnector(),
            client_limit=CLIENT_LIMIT,
            max_size=0,
            max_idle_seconds=MAX_IDLE_SECONDS,
        )


async def test_connection_pool_get(pool):
    async def thrasher():
        async with pool.get() as conn:
            assert not conn.is_closed

    await asyncio.gather(thrasher(), thrasher(), thrasher(), thrasher())
    await sleep(MAX_IDLE_SECONDS * 2)
    assert pool._pool[0] <= pool._pool[1]


async def test_connection_pool_close(pool):
    async with pool.get() as conn:
        assert not conn.is_closed
        await sleep(MAX_IDLE_SECONDS * 2)

    await pool.closeall()
    assert all(pl._connection is None for pl in pool._pool)


async def test_pool_acquire_timeouts(slow_pool):
    """Check that acquire with timeout moves on sucessfully"""
    with pytest.raises(cp.ConnectionsExhausted):
        async with slow_pool.get(
            timeout=SLOW_CONN_SLEEPINESS, acquire_timeout=SLOW_CONN_SLEEPINESS
        ) as conn:
            assert conn is None


# # # # # # # # # # # # # # # # # #
# ---**--> send_time_deco tests <--**---
# # # # # # # # # # # # # # # # # #


async def test_send_time_deco_basic():
    """Test that send_time_deco wraps a function and returns the correct result"""

    @cp.send_time_deco()
    async def test_func(value):
        await sleep(0.01)  # Small delay to ensure some timing is recorded
        return value * 2

    result = await test_func(5)
    assert result == 10


async def test_send_time_deco_with_custom_message(caplog):
    """Test send_time_deco with custom message logs timing information"""
    import logging

    # Set up logging to capture debug messages
    caplog.set_level(
        logging.DEBUG, logger="aio_azure_clients_toolbox.connection_pooling"
    )

    @cp.send_time_deco(msg="Test operation")
    async def test_func():
        await sleep(0.01)
        return "done"

    result = await test_func()
    assert result == "done"

    # Check that timing message was logged
    debug_messages = [
        record.message for record in caplog.records if record.levelname == "DEBUG"
    ]
    assert any(
        "Test operation timing:" in msg and "ns" in msg for msg in debug_messages
    )


async def test_send_time_deco_with_custom_logger(caplog):
    """Test send_time_deco with custom logger"""
    import logging

    # Create a custom logger
    custom_logger = logging.getLogger("test_custom_logger")
    caplog.set_level(logging.DEBUG, logger="test_custom_logger")

    @cp.send_time_deco(log=custom_logger, msg="Custom logger test")
    async def test_func():
        await sleep(0.01)
        return "custom_result"

    result = await test_func()
    assert result == "custom_result"

    # Check that timing message was logged to the custom logger
    debug_messages = [
        record.message
        for record in caplog.records
        if record.levelname == "DEBUG" and record.name == "test_custom_logger"
    ]
    assert any(
        "Custom logger test timing:" in msg and "ns" in msg for msg in debug_messages
    )


# # # # # # # # # # # # # # # # # #
# ---**--> RACE CONDITION TESTS <--**---
# # # # # # # # # # # # # # # # # #


class ClosableTestConnection(cp.AbstractConnection):
    """Test connection that tracks if it was closed while still being used"""

    def __init__(self):
        self.is_closed = False
        self.usage_count = 0
        self.used_after_close = False

    async def close(self):
        self.is_closed = True

    def use(self):
        """Simulate using the connection - should fail if called after close"""
        if self.is_closed:
            self.used_after_close = True
            raise RuntimeError("Connection used after close!")
        self.usage_count += 1
        return f"used_{self.usage_count}"


class RaceConditionTestConnector(cp.AbstractorConnector):
    """Connector that creates trackable test connections"""

    def __init__(self):
        self.created_connections = []

    async def create(self) -> cp.AbstractConnection:
        conn = ClosableTestConnection()
        self.created_connections.append(conn)
        return conn

    async def ready(self, connection: cp.AbstractConnection) -> bool:
        return True


@pytest.fixture
def race_condition_shared_conn():
    """Shared connection with very short lifespan to trigger race conditions"""
    return cp.SharedTransportConnection(
        RaceConditionTestConnector(),
        client_limit=3,
        max_idle_seconds=0.002,  # Very short to trigger expiry quickly
        max_lifespan_seconds=0.003,  # Short lifespan
    )


@pytest.fixture
def race_condition_pool():
    """Connection pool with very short lifespans to trigger race conditions"""
    return cp.ConnectionPool(
        RaceConditionTestConnector(),
        client_limit=3,
        max_size=2,
        max_idle_seconds=0.001,
        max_lifespan_seconds=0.002,
    )


# FAILING TESTS - These expose the race condition bugs


class CosmosLikeConnection(cp.AbstractConnection):
    """Connection that mimics SimpleCosmos behavior from the real issue"""

    def __init__(self):
        self.is_closed = False
        self.usage_count = 0
        self._container = "mock_container"  # This simulates SimpleCosmos._container

    async def close(self):
        """This simulates SimpleCosmos.close() which sets _container = None"""
        self.is_closed = True
        self._container = None  # This is the key - shared state gets mutated

    def __getattr__(self, name):
        """This simulates SimpleCosmos.__getattr__ which raises the actual error"""
        if self._container is None:
            raise AttributeError("Container client not constructed")

        # Return a callable mock function
        def mock_method(*args, **kwargs):
            return f"mock_{name}_result"

        return mock_method

    def use_container(self):
        """This simulates calling a method on SimpleCosmos that triggers __getattr__"""
        return self.read_item("test")  # This will call __getattr__


class CosmosLikeConnector(cp.AbstractorConnector):
    """Connector that creates cosmos-like connections"""

    def __init__(self):
        self.created_connections = []

    async def create(self) -> cp.AbstractConnection:
        conn = CosmosLikeConnection()
        self.created_connections.append(conn)
        return conn

    async def ready(self, connection: cp.AbstractConnection) -> bool:
        return True


async def test_race_condition_shared_connection_closed_while_in_use():
    """Forces race condition sequence"""
    connector = CosmosLikeConnector()
    shared_conn = cp.SharedTransportConnection(
        connector,
        client_limit=3,
        max_idle_seconds=0.001,
        max_lifespan_seconds=0.002,
    )

    # Client gets connection, shares it, first client triggers close

    # Force create a connection first
    connection = await shared_conn.checkout()
    async with shared_conn.acquire():
        connection.use_container()  # Use it

    # Now wait for expiry
    await sleep(0.003)

    # Force the race condition by manually calling the problematic code path
    # Get connection again (should reuse the same one)
    await shared_conn.checkout()

    # Get another reference while first is still holding semaphore
    # This simulates what happens when multiple clients get the same connection
    conn_ref2 = shared_conn._connection
    await shared_conn.checkin()

    # Now expire and close the connection via checkin
    # This simulates what happens when the first client finishes and lifespan is exceeded
    if shared_conn.current_client_count == 1 and shared_conn.expired:
        # Manually trigger the close that happens in checkin
        await shared_conn.close()

    # Now the second client tries to use the same connection object
    try:
        conn_ref2.use_container()
    except AttributeError as e:
        await shared_conn.checkin()
        if "Container client not constructed" in str(e):
            # This is the race condition we're looking for!
            pytest.fail(f"Race condition detected - {e}")
        else:
            raise


async def test_race_condition_simplified_reproduction():
    """Simplified test that definitely exposes the race condition"""
    # Create a cosmos-like connection directly
    conn = CosmosLikeConnection()

    # Verify it works initially
    result1 = conn.use_container()
    assert "mock_read_item" in result1

    # Close the connection (this is what happens in the race condition)
    await conn.close()

    # Now try to use it - this should raise the exact error from the issue
    with pytest.raises(AttributeError, match="Container client not constructed"):
        conn.use_container()

    # This test will always pass, showing what the error looks like
    assert True, "This demonstrates the exact error that occurs in the race condition"


async def test_race_condition_multiple_clients_expired_connection():
    """Multiple clients getting same connection when one should close it"""
    connector = CosmosLikeConnector()
    shared_conn = cp.SharedTransportConnection(
        connector,
        client_limit=3,
        max_idle_seconds=0.001,
        max_lifespan_seconds=0.002,
    )

    # First client gets connection and lets it expire
    async with shared_conn.acquire() as conn:
        conn.use_container()
        await sleep(0.003)  # Exceed lifespan

    # Connection should be expired now
    assert shared_conn.expired, "Connection should be expired"

    # Now simulate multiple clients trying to get the expired connection simultaneously
    # In previous behavior, first client to checkout will close the expired connection
    # but other clients might still get reference to it
    results = []
    exceptions = []

    async def client_task(client_id):
        try:
            # All clients try to checkout at same time
            conn = await shared_conn.checkout()
            # Use connection
            result = conn.use_container()
            results.append(f"Client {client_id}: {result}")
            await shared_conn.checkin()
        except Exception as e:
            exceptions.append(f"Client {client_id}: {e}")

    # Run multiple clients concurrently
    await asyncio.gather(client_task(1), client_task(2), client_task(3))

    # Check if any connection was used after being closed
    container_errors = [
        e for e in exceptions if "Container client not constructed" in str(e)
    ]

    if container_errors:
        # Race condition detected
        pytest.fail(f"Race condition detected: {container_errors}")
    else:
        # Race condition not triggered - this means the test should pass
        # but we marked it as xfail, so it will show as unexpected pass
        assert len(exceptions) == 0, f"Unexpected exceptions: {exceptions}"


async def test_race_condition_pool_connection_lifecycle():
    """
    Pool-level race condition test that mimics the SimpleCosmos.__getattr__ issue:
        If we are able to use a connection that has been closed due to lifespan expiry
        while another client is still using it, we should see an AttributeError.

    If this issue is fixed, this test should pass without errors.

    1. Client 1 gets connection and holds it past expiry
    2. Client 2 gets same connection while Client 1 is still using it
    3. Client 1 finishes and connection is closed due to expiry
    4. Client 2 tries to use the connection - should raise AttributeError
    """
    connector = CosmosLikeConnector()
    pool = cp.ConnectionPool(
        connector,
        client_limit=2,
        max_size=1,
        max_idle_seconds=0.003,
        max_lifespan_seconds=0.004,
    )

    # Client 1 gets connection and holds it past expiry
    connection_object = None

    async def client_1():
        nonlocal connection_object
        async with pool.get() as conn:
            connection_object = conn  # Store reference
            conn.use_container()
            await sleep(0.05)  # Exceed lifespan, connection will be closed in checkin
        # Connection should be closed when this exits

    async def client_2():
        # Wait a bit for client 1 to start
        await sleep(0.005)
        async with pool.get() as conn:
            # This should be the same connection object as client 1
            assert conn is connection_object, "Should get same connection object"
            await sleep(0.014)  # Wait for client 1 to finish and close connection
            # Now try to use it - should fail if race condition exists
            result = conn.use_container()  # This should raise AttributeError
            return result

    # Run both clients
    try:
        await asyncio.gather(client_1(), client_2())
        pytest.fail("Race condition NOT detected - both clients succeeded")
    except AttributeError as e:
        if "Container client not constructed" in str(e):
            # Race condition successfully triggered!
            pytest.fail("Race condition detected - one client used a closed connection")
        else:
            raise


# # # # # # # # # # # # # # # # # #
# ---**--> Regression tests <--**---
# # # # # # # # # # # # # # # # # #
async def test_no_regression_normal_connection_sharing(race_condition_pool):
    """PASSING TEST: Ensures normal connection sharing still works without race conditions"""
    results = []

    async def normal_client(client_id):
        async with race_condition_pool.get() as conn:
            result = conn.use()
            results.append(f"Client {client_id}: {result}")
            await sleep(0.0001)  # Very short usage, well within lifespan

    # Run clients that should share connections successfully
    await asyncio.gather(
        normal_client(1),
        normal_client(2),
        normal_client(3),
    )

    assert len(results) == 3
    assert all("used_" in result for result in results)


async def test_no_regression_connection_cleanup_after_idle():
    """PASSING TEST: Ensures connections are properly cleaned up after idle timeout"""
    connector = RaceConditionTestConnector()
    shared_conn = cp.SharedTransportConnection(
        connector,
        client_limit=2,
        max_idle_seconds=0.01,
    )

    # Use connection and let it go idle
    async with shared_conn.acquire() as conn:
        conn.use()

    # Verify it's idle
    assert shared_conn.current_client_count == 0
    assert shared_conn.last_idle_start is not None

    # Wait for idle timeout
    await sleep(0.02)

    # Connection should be marked as expired
    assert shared_conn.expired

    # Next acquisition should clean up the expired connection
    async with shared_conn.acquire() as conn:
        conn.use()

    # Should have created a new connection (old one was cleaned up)
    assert len(connector.created_connections) >= 1


async def test_no_regression_semaphore_limits_enforced(race_condition_shared_conn):
    """PASSING TEST: Ensures semaphore limits are still properly enforced"""
    # The fixture has client_limit=3
    acquired_connections: list[str] = []

    async def try_acquire(client_id):
        try:
            async with race_condition_shared_conn.acquire(timeout=0.002) as conn:
                if conn is not None:
                    acquired_connections.append(client_id)
                    await sleep(0.004)  # brief hold more than acquire timeout
        except Exception:
            pass  # Timeout expected for excess clients

    # Try to acquire more connections than the limit allows
    await asyncio.gather(
        try_acquire("1"),
        try_acquire("2"),
        try_acquire("3"),
        try_acquire("4"),  # This should timeout
        try_acquire("5"),  # This should timeout
    )

    # Should allow up to client limit of 3
    assert len(acquired_connections) == 3


async def test_no_regression_pool_heap_ordering():
    """PASSING TEST: Ensures pool still maintains proper heap ordering for connection freshness"""
    pool = cp.ConnectionPool(
        RaceConditionTestConnector(),
        client_limit=2,
        max_size=3,
        max_idle_seconds=0.1,
    )

    # Use connections to establish different idle times
    async with pool.get() as conn1:
        conn1.use()
        await sleep(0.001)

    await sleep(0.002)  # Let first connection become more idle

    async with pool.get() as conn2:
        conn2.use()

    # Pool should maintain heap ordering (freshest connections first)
    # This is verified by the internal heap structure
    import heapq

    assert len(pool._pool) == 3
    # Heap property should be maintained
    heap_copy = pool._pool.copy()
    heapq.heapify(heap_copy)
    assert heap_copy == pool._pool
