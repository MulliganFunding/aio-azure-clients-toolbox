import asyncio

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
        max_idle_seconds=0.001,  # Very short to trigger expiry quickly
        max_lifespan_seconds=0.002,  # Even shorter lifespan
    )


@pytest.fixture
def race_condition_pool():
    """Connection pool with very short lifespans to trigger race conditions"""
    return cp.ConnectionPool(
        RaceConditionTestConnector(),
        client_limit=3,
        max_size=1,
        max_idle_seconds=0.001,
        max_lifespan_seconds=0.002,
    )


# FAILING TESTS - These expose the race condition bugs


# @pytest.mark.xfail(
#     reason="Race condition: connection closed while other clients still using it"
# )
async def test_race_condition_lifespan_expiry_during_usage(race_condition_shared_conn):
    """FAILING TEST: Exposes race condition where connection gets closed while other clients are using it"""
    results = []
    exceptions = []

    async def client_a():
        """Client that will trigger the expiry"""
        try:
            async with race_condition_shared_conn.acquire() as conn:
                conn.use()  # Use connection
                await sleep(0.003)  # Hold it past lifespan
                results.append("Client A done")
        except Exception as e:
            exceptions.append(("Client A", e))

    async def client_b():
        """Client that gets same connection but may find it closed"""
        try:
            await sleep(0.001)  # Let client A get connection first
            async with race_condition_shared_conn.acquire() as conn:
                await sleep(0.001)  # Let client A potentially close connection
                result = conn.use()  # This should fail if connection was closed
                results.append(f"Client B: {result}")
        except Exception as e:
            exceptions.append(("Client B", e))

    # Run both clients concurrently
    await asyncio.gather(client_a(), client_b())

    # If race condition exists, client B should get an exception
    # because the connection was closed while it was still using it
    assert len(exceptions) == 0, f"Race condition detected: {exceptions}"
    assert len(results) == 2, f"Expected 2 successful results, got: {results}"


# @pytest.mark.xfail(
#     reason="Race condition: connection expires during checkout-checkin window"
# )
async def test_race_condition_checkout_expiry_window(race_condition_shared_conn):
    """FAILING TEST: Exposes race condition in checkout when connection expires"""

    # First, let's create and expire a connection
    async with race_condition_shared_conn.acquire() as conn:
        conn.use()

    # Wait for expiry
    await sleep(0.005)

    # Now multiple clients try to get the expired connection simultaneously
    results = []
    exceptions = []

    async def concurrent_client(client_id):
        try:
            async with race_condition_shared_conn.acquire() as conn:
                if conn is None:
                    results.append(f"Client {client_id}: None")
                else:
                    result = conn.use()
                    results.append(f"Client {client_id}: {result}")
        except Exception as e:
            exceptions.append((f"Client {client_id}", e))

    # Run multiple clients concurrently to trigger race condition in checkout
    await asyncio.gather(
        concurrent_client(1), concurrent_client(2), concurrent_client(3)
    )

    # Check that no client got a closed connection
    assert len(exceptions) == 0, f"Race condition in checkout: {exceptions}"
    closed_usage = any("used after close" in str(e) for _, e in exceptions)
    assert not closed_usage, "Connection was used after being closed"


# @pytest.mark.xfail(reason="Race condition: pool yields closed connections")
async def test_race_condition_pool_yields_closed_connection(race_condition_pool):
    """FAILING TEST: Exposes race condition where pool yields closed connections"""
    exceptions = []
    results = []

    async def client_with_delay(client_id, delay):
        try:
            await sleep(delay)
            async with race_condition_pool.get() as conn:
                if conn is None:
                    results.append(f"Client {client_id}: None")
                else:
                    result = conn.use()
                    results.append(f"Client {client_id}: {result}")
                    # Hold connection to trigger expiry
                    await sleep(0.003)
        except Exception as e:
            exceptions.append((f"Client {client_id}", e))

    # Start multiple clients with staggered timing
    await asyncio.gather(
        client_with_delay(1, 0.0),  # Starts immediately
        client_with_delay(2, 0.001),  # Starts slightly later
        client_with_delay(3, 0.002),  # Starts even later
    )

    # Check for race condition indicators
    assert len(exceptions) == 0, f"Race condition detected: {exceptions}"
    used_after_close_errors = [
        e for _, e in exceptions if "Connection used after close" in str(e)
    ]
    assert len(used_after_close_errors) == 0, "Connection was used after being closed"


# PASSING TESTS - These verify existing behavior and catch regressions


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
    acquired_connections = []

    async def try_acquire(client_id):
        try:
            async with race_condition_shared_conn.acquire(timeout=0.01) as conn:
                if conn is not None:
                    acquired_connections.append(client_id)
                    await sleep(
                        0.02
                    )  # Hold connection longer than timeout to block others
        except Exception:
            pass  # Timeout expected for excess clients

    # Try to acquire more connections than the limit allows
    await asyncio.gather(
        try_acquire(1),
        try_acquire(2),
        try_acquire(3),
        try_acquire(4),  # This should timeout
        try_acquire(5),  # This should timeout
    )

    # Should not exceed the client limit of 3
    assert len(acquired_connections) <= 3


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
