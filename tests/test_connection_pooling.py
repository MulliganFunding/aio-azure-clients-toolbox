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
        async with slow_pool.get(timeout=SLOW_CONN_SLEEPINESS) as conn:
            assert conn is None
