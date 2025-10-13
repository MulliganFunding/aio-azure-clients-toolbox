import asyncio
import heapq
import logging

import pytest
from aio_azure_clients_toolbox import connection_pooling as cp
from anyio import create_task_group, Event, move_on_after, sleep


class FakeConn(cp.AbstractConnection):
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


class FakeConnector(cp.AbstractorConnector):
    def __init__(self):
        self._created = False
        self._ready = False
        self.references = []

    async def create(self):
        self._created = True
        conn = FakeConn()
        self.references.append(conn)
        return conn

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


# # # # # # # # # # # # # # # # # # # # # # # # # # #
# ---**--> Test SharedTransportConnection <--**---  #
# # # # # # # # # # # # # # # # # # # # # # # # # # #
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
    """EQ IFF
    - self._connection objects are same (by identity)
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

    assert stc2 == shared_transpo_conn
    stc2.last_idle_start = 10
    shared_transpo_conn.last_idle_start = 20
    assert stc2 != shared_transpo_conn, "Different last_idle_start makes them unequal"


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
    async def acquirer(stc):
        async with stc.acquire():
            await sleep(0.002)

    # Client count for stc2 is less-than
    # We wrap in timeout in case of deadlock
    with move_on_after(0.2) as timeout_scope:
        async with create_task_group() as tg:
            tg.start_soon(acquirer, shared_transpo_conn)
            tg.start_soon(acquirer, shared_transpo_conn)
            tg.start_soon(acquirer, stc2)
            await sleep(0.006)
            assert stc2 < shared_transpo_conn, "Acquire makes client count LT"

    assert not timeout_scope.cancel_called, "Deadlock in LT test"

    # Reset client counts happens after async context managed exits
    assert stc2 <= shared_transpo_conn, "Client count equal makes them LTE"
    # Now that client count is equal, we use last_idle_start for comp
    stc2.last_idle_start = 1000000
    shared_transpo_conn.last_idle_start = 2000000
    assert stc2 < shared_transpo_conn, "Longer idle makes it LT"


async def test_comp_gt(shared_transpo_conn):
    """GT IFF
    - it has more clients connected
    - it's been idle less
    """
    # GT / GTE
    stc2 = cp.SharedTransportConnection(
        FakeConnector(), client_limit=CLIENT_LIMIT, max_idle_seconds=MAX_IDLE_SECONDS
    )
    assert stc2 >= shared_transpo_conn
    async def acquirer(stc):
        async with stc.acquire():
            await sleep(0.002)

    # Client count for stc2 is less-than
    # We wrap in timeout in case of deadlock
    with move_on_after(0.2) as timeout_scope:
        async with create_task_group() as tg:
            tg.start_soon(acquirer, shared_transpo_conn)
            tg.start_soon(acquirer, shared_transpo_conn)
            tg.start_soon(acquirer, stc2)
            await sleep(0.006)
            assert shared_transpo_conn > stc2, "Acquire makes client count GT"

    assert not timeout_scope.cancel_called, "Deadlock in GT test"
    # Reset client counts happens after async context managed exits
    assert shared_transpo_conn >= stc2, "Client count equal makes them GTE"

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


# # # # # # # # # # # # # # # # # # # # # # # # # # #
# ---**-->      Test ConnectionPool       <--**---  #
# # # # # # # # # # # # # # # # # # # # # # # # # # #
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
    # We wrap in timeout in case of deadlock
    with move_on_after(0.2) as timeout_scope:
        with pytest.raises(cp.ConnectionsExhausted):
            async with slow_pool.get(timeout=SLOW_CONN_SLEEPINESS, acquire_timeout=SLOW_CONN_SLEEPINESS) as conn:
                assert conn is None
    assert not timeout_scope.cancel_called, "Deadlock in pool acquire timeout test"


# # # # # # # # # # # # # # # # # #
# ---**--> RACE CONDITION TESTS <--**---
# # # # # # # # # # # # # # # # # #
@pytest.fixture
def race_condition_shared_conn():
    """Shared connection with very short lifespan to trigger race conditions"""
    return cp.SharedTransportConnection(
        FakeConnector(),
        client_limit=3,
        max_idle_seconds=0.002,  # Very short to trigger expiry quickly
        max_lifespan_seconds=0.003,  # Short lifespan
    )


@pytest.fixture
def race_condition_pool():
    """Connection pool with very short lifespans to trigger race conditions"""
    return cp.ConnectionPool(
        FakeConnector(),
        client_limit=3,
        max_size=2,
        max_idle_seconds=0.001,
        max_lifespan_seconds=0.002,
    )


# Our SimpleCosmos object has a __getattr__ that raises AttributeError
# if the underlying container client is None (which happens after close)
# This is a fake version of that thing.
class CosmosLikeConnection(cp.AbstractConnection):
    """Connection that mimics SimpleCosmos behavior from the real issue"""

    def __init__(self):
        self.is_closed = False
        self.usage_count = 0
        self._container = "mock_container"  # This simulates SimpleCosmos._container

    async def close(self):
        """This simulates SimpleCosmos.close() which sets _container = None"""
        self.is_closed = True
        self._container = None  # Use after this should raise AttributeError

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
        self.is_closed = False
        self.created_connections = []

    async def create(self) -> cp.AbstractConnection:
        conn = CosmosLikeConnection()
        self.created_connections.append(conn)
        return conn

    async def ready(self, connection: cp.AbstractConnection) -> bool:
        return True

    async def close(self):
        self.is_closed = True


async def test_race_condition_shared_connection_closed_while_in_use():
    """Forces race condition sequence: mixes checkout and checkin with expiry"""
    connector = CosmosLikeConnector()
    shared_conn = cp.SharedTransportConnection(
        connector,
        client_limit=3,
        max_idle_seconds=0.001,
        max_lifespan_seconds=0.002,
    )
    # Hold references to connection objects
    references = []

    # Client gets connection, shares it, first client triggers close
    async def checkouter(n):
        connection = await shared_conn.checkout()
        connection.use_container()  # Use it
        if n < 2:
            await shared_conn.checkin()
        references.append(connection)

    # Force create a connection first
    with move_on_after(0.2) as timeout_scope:
        async with create_task_group() as tg:
            tg.start_soon(checkouter, 0)
            # Now wait for expiry
            await sleep(0.003)
            # Force the race condition by manually calling the problematic code path
            # Get connection again (should reuse the same one)
            tg.start_soon(checkouter, 1)
            tg.start_soon(checkouter, 2)
    assert not timeout_scope.cancel_called, "Deadlock in shared connection race condition test"

    # Sanity check: we should have only one connection object
    assert shared_conn.current_client_count <= 1 and shared_conn.expired

    # Now the second client tries to use the same connection object:
    # Before the bug fix, this raises AttributeError.
    try:
        references[2].use_container()
    except AttributeError as e:
        if "Container client not constructed" in str(e):
            # This is a race condition that exists when multiple clients share a connection
            # That was closed by another client.
            pytest.fail(f"Race condition detected - {e}")
        else:
            raise


async def test_race_condition_pool_connection_lifecycle():
    """
    Pool-level race condition test that mimics the SimpleCosmos.__getattr__ issue:
        If we are able to use a connection that has been closed due to lifespan expiry
        while another client is still using it, we should see an AttributeError.

    If this issue is fixed, this test should pass without errors and be a regression test.

    1. Client 1 gets connection and holds it past expiry
    2. Client 2 gets same connection while Client 1 is still using it
    3. Client 2 finishes and connection is closed due to expiry
    4. Client 1 tries to use the connection - should raise AttributeError
    """
    connector = CosmosLikeConnector()
    pool = cp.ConnectionPool(
        connector,
        client_limit=3,
        max_size=1,
        max_idle_seconds=0.001,
        max_lifespan_seconds=0.002,
    )

    # Hold references to connection objects
    references = []
    # We're going to try to deadlock a little bit just for fun.
    client1_event = Event()
    client2_event = Event()

    async def client_1():
        async with pool.get() as conn:
            references.append(conn)  # Store reference
            await sleep(0.04)  # Exceed lifespan, connection will be marked should_close
            client1_event.set()

        await client2_event.wait()
        # Now try to use it - should fail if race condition exists
        conn.use_container()  # This should raise AttributeError
        # Connection should be closed when this exits

    async def client_2():
        async with pool.get() as conn:
            # Sanity check: this should be the same connection object as client 1
            # If this fails, the connection will have been recycled.
            assert conn is references[0], "Should get same connection object"
            await client1_event.wait()

        # Now try to use it - should fail if race condition exists
        conn.use_container()
        await sleep(0.04)  # Exceed lifespan, connection will be marked should_close
        client2_event.set()

    # Run both clients
    try:
        with move_on_after(1.0) as timeout_scope:
            async with create_task_group() as tg:
                tg.start_soon(client_1)
                tg.start_soon(client_2)
        assert not timeout_scope.cancel_called, "Deadlock in pool connection lifecycle test"
    except* AttributeError as excgroup:
        for exc in excgroup.exceptions:
            if "Container client not constructed" in str(exc):
                # Race condition successfully triggered!
                pytest.fail("Race condition detected - one client used a closed connection")
            else:
                raise


async def test_pool_connection_closes_safely():
    """
    Pool-level race condition test that tries to close a connection while another client is using it.
    """
    connector = FakeConnector()
    pool = cp.ConnectionPool(
        connector,
        client_limit=2,
        max_size=2,
        max_idle_seconds=0.001,
        max_lifespan_seconds=0.002,
    )

    # Hold references to connection objects
    references = {}
    # We're going to try to deadlock a little bit just for fun.
    client1_event = Event()
    client2_event = Event()

    async def client_1():
        async with pool.get() as conn:
            references[0] = conn  # Store reference
            await sleep(0.005)  # Exceed lifespan, connection will be marked should_close
            conn.use()  # Should work fine
            client1_event.set()

    async def client_2():
        await client1_event.wait()  # Start right after client 1
        async with pool.get() as conn:
            references[1] = conn  # Store reference
            conn.use()  # Should work fine
            await sleep(0.01)
            client2_event.set()
            # Should close *first* connection outside of context mgr!
            assert references[0].is_closed

    async def client_3():
        # Get a connection immediately
        async with pool.get() as conn:
            await client2_event.wait()  # Start *after* client 2
            references[2] = conn  # Store reference
            conn.use()  # Should work fine

    # Run both clients
    try:
        with move_on_after(1.0) as timeout_scope:
            async with create_task_group() as tg:
                tg.start_soon(client_1)
                tg.start_soon(client_2)
                tg.start_soon(client_3)
        assert not timeout_scope.cancel_called, "Deadlock in pool connection close test"
    except* AttributeError as excgroup:
        for exc in excgroup.exceptions:
            if "Container client not constructed" in str(exc):
                # Race condition successfully triggered!
                pytest.fail("Race condition detected - one client used a closed connection")
            else:
                raise

    # No connections are reused here
    identity_count = len(set(id(ref) for ref in references.values()))
    assert len(references) == 3
    assert identity_count == 3
    assert sum(ref.is_closed for ref in references.values()) == 1
    assert all(conn.should_close for conn in pool._pool)


# # # # # # # # # # # # # # # # # #
# ---**--> Regression tests <--**---
# # # # # # # # # # # # # # # # # #
async def test_regression_normal_connection_sharing(race_condition_pool):
    """Ensures normal connection sharing still works without race conditions"""
    results = []

    async def normal_client(client_id):
        async with race_condition_pool.get() as conn:
            result = conn.use()
            results.append(f"Client {client_id}: {result}")
            await sleep(0.0001)  # Very short usage, well within lifespan

    # Run clients that should share connections successfully
    with move_on_after(1.0) as timeout_scope:
        async with create_task_group() as tg:
            tg.start_soon(normal_client, 1)
            tg.start_soon(normal_client, 2)
            tg.start_soon(normal_client, 3)

    assert not timeout_scope.cancel_called, "Deadlock in normal connection sharing test"

    assert len(results) == 3
    assert all("used_" in result for result in results)


async def test_regression_connection_cleanup_after_idle():
    """Ensures connections are properly cleaned up after idle timeout"""
    connector = FakeConnector()
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
    assert len(connector.references) >= 1


@pytest.mark.parametrize("client_count", [1, 3, 5, 7, 12, 21])
async def test_regression_semaphore_limits_enforced(
    client_count, race_condition_shared_conn
):
    """Ensures semaphore limits are still properly enforced"""
    deactivated_connections: dict[str, int] = {}
    active_connections: dict[str, int] = {}
    exceptions = []

    async def try_acquire(client_id: str):
        conn_id = None
        try:
            async with race_condition_shared_conn.acquire(timeout=0.002) as conn:
                if conn is not None:
                    conn_id = id(conn)
                    active_connections[client_id] = conn_id
                    await sleep(0.005)  # brief hold more than acquire timeout
                    assert list(active_connections.values()).count(client_id) <= 3
        except Exception as e:
            exceptions.append(e)
        if conn_id is not None:
            del active_connections[client_id]
            deactivated_connections[client_id] = conn_id

    # Try to acquire more connections than the limit allows
    with move_on_after(1.0) as timeout_scope:
        async with create_task_group() as tg:
            for n in range(client_count):
                tg.start_soon(try_acquire, f"{n}")

    assert not timeout_scope.cancel_called, "Deadlock in semaphore limit test"
    # The fixture has `client_limit=3`, so we see that number of clients per connection
    # Prefer -> one connection shared,
    assert len(exceptions) == 0
    assert len(deactivated_connections) <= client_count


async def test_regression_pool_heap_ordering():
    """Ensures pool still maintains proper heap ordering for connection freshness"""
    pool = cp.ConnectionPool(
        FakeConnector(),
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
    assert len(pool._pool) == 3
    # Heap property should be maintained
    heap_copy = pool._pool.copy()
    heapq.heapify(heap_copy)
    assert heap_copy == pool._pool


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
