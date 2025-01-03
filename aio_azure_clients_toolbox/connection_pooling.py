"""
connection_pooling.py

The idea for our Azure clients is that unlike database connections
*all of our clients can be reused* across multiple requesters.

What we really need to achieve is the following:
- A "pool" of connections, where
- Each connection may be shared by more than 1 requester, and
- Each connection has an idle lifespan.

The latter is the most important because Azure will enforce
idle timeouts for *all sockets*. For this reason, we will do the following:
- lazily create connections as needed
- share connections between many requesters
- put connections back into an idle data structure when necessary
- when connections are dead (exception or idle timeout) then we'll lock and recreate
- when a connection has exceeded its "share" amount, we'll lock and create a new one.
"""

import binascii
import heapq
import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import total_ordering, wraps

import anyio
from anyio import create_task_group, move_on_after

DEFAULT_MAX_SIZE = 10
DEFAULT_CONNECTION_MAX_IDLE_SECONDS = 300
DEFAULT_SHARED_TRANSPORT_CLIENT_LIMIT = 100
NANO_TIME_MULT = 1_000_000_000
logger = logging.getLogger(__name__)


class ConnectionsExhausted(ValueError):
    pass


class ConnectionFailed(ConnectionError):
    pass


class AbstractConnection(ABC):
    @abstractmethod
    async def close(self): ...


class AbstractorConnector(ABC):
    @abstractmethod
    async def create(self) -> AbstractConnection: ...

    @abstractmethod
    async def ready(self, connection: AbstractConnection) -> bool: ...


def send_time_deco(log=None, msg: str = ""):
    """
    Checking the timing required to invoke: useful for checking if
    acquiring a connection takes a long time. Wraps an async function
    that acquires and uses a connection pool connection!

    Pass the logger you want to use and a sample message.
    """
    _logger = log
    if _logger is None:
        _logger = logger

    def send_time_deco_wrapper(fn):
        @wraps(fn)
        async def inner(*args, **kwargs):
            now = time.monotonic_ns()
            result = await fn(*args, **kwargs)
            timing = time.monotonic_ns() - now
            if msg:
                message = f"{msg} timing: {timing}ns"
            else:
                message = f"Connection pool using function timing: {timing}ns"
            _logger.debug(message)
            return result

        return inner

    return send_time_deco_wrapper


@total_ordering
class SharedTransportConnection:
    """
    Each connection can be shared by many clients.

    The problem we need to solve for most pressingly is idle timeouts, but
    we also have problems around *opening*, establishing, and *closing* connections.

    Thus, each connection has the following lifecycle phases:

    - Closed
    - Open and not ready
    - Open and ready

    These are also the critical sections of work, so transitioning from one phase
    to another involves *locking* the resource.

    The problem is that when a client first attempts to *use* a connection, it calls
    one of the network-communication methods, and at that point, the connection
    is established. To *other* clients who are `await`ing their turn, the connection
    *already looks open*, so they may try to use it early and fail. The same problem
    happens on closing: one client closes while another still thinks the connection is live.

    Outside of this, after we have sent for the first time, we're fine to share the connection
    as much as we want. Thus, we need to lock out all clients during its critical sections of work:

    - Lock this connection when *opening* an underlying connection
    - Lock this connection when *establishing "readiness"* (first usage)
    - Lock this connection when *closing* an underlying connection

    At all other points we can share it a whole lot (between 100 clients or more). To see what's
    happening, enable debug logs:
        logger.getLogger("aio_azure_clients_toolbox").setLevel(logging.DEBUG)

    Footnote: most Azure sdk clients use aiohttp shared transports below
    the surface which actually has threadpooling with up to 100 connections. We wanted something
    more generic, though, which is why this class exists.

    Azure Python SDK has an example of a shared transport for Azure clients
    but we wanted to start simpler and more agnostic here:

    https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/core/azure-core/samples/example_shared_transport_async.py#L51-L71

    Based on the Azure example, though, we should easily be able to share one of these "connection"
    objects with 100 requesters.

    Args:
      connector:
        An instance of an AbstractConnector for creating connections.
      client_limit:
        The max clients allowed _per_ connection (default: 100).
      max_idle_seconds:
        Maximum duration allowed for an idle connection before recylcing it.
      max_lifespan_seconds:
        Optional setting which controls how long a connection live before recycling.
    """

    __slots__ = (
        "last_idle_start",
        "max_idle_ns",
        "max_lifespan_ns",
        "max_clients_allowed",
        "client_limiter",
        "connection_created_ts",
        "_connector",
        "_connection",
        "_open_close_lock",
        "_id",
        "_ready",
    )

    def __init__(
        self,
        connector: AbstractorConnector,
        client_limit: int = DEFAULT_SHARED_TRANSPORT_CLIENT_LIMIT,
        max_lifespan_seconds: int | None = None,
        max_idle_seconds: int = DEFAULT_CONNECTION_MAX_IDLE_SECONDS,
    ) -> None:
        # When was this connection created
        self.connection_created_ts: int | None = None
        # When did this connection last become idle
        self.last_idle_start: int | None = None
        # What's the max lifespan (idle or active) allowed for this connection
        if max_lifespan_seconds is None:
            # If `None`, this feature is disabled
            self.max_lifespan_ns = None
        else:
            self.max_lifespan_ns = max_lifespan_seconds * NANO_TIME_MULT

        self.max_clients_allowed = client_limit
        # What's the max idle time allowed for this connection
        self.max_idle_ns = max_idle_seconds * NANO_TIME_MULT
        # How many clients are allowed
        self.client_limiter = anyio.CapacityLimiter(total_tokens=client_limit)

        self._connector: AbstractorConnector = connector
        self._connection: AbstractConnection | None = None
        self._open_close_lock: anyio.Lock = anyio.Lock()
        self._id = (binascii.hexlify(os.urandom(3))).decode()
        self._ready = anyio.Event()

    def __bool__(self):
        if self._connection is None:
            return False
        return self.is_ready and not self.expired

    def eq(self, connection: AbstractConnection) -> bool:
        return self._connection is connection

    @property
    def available(self):
        """Check if connection exists and client usage limit has been reached"""
        return self.current_client_count < self.max_clients_allowed

    @property
    def current_client_count(self):
        return self.client_limiter.borrowed_tokens

    @property
    def expired(self) -> bool:
        """Calculate if connection has been idle or active longer than allowed"""
        if self._connection is None:
            return False

        if self.max_lifespan_ns is not None and self.connection_created_ts is not None:
            lifetime_expired = self.lifetime > self.max_lifespan_ns
        else:
            lifetime_expired = False

        # Check if time limit has been exceeded
        return self.time_spent_idle > self.max_idle_ns or lifetime_expired

    @property
    def lifetime(self) -> int:
        """Check the lifetime of this object (in nanos)"""
        if self.connection_created_ts is None:
            return 0

        now = time.monotonic_ns()
        return now - self.connection_created_ts

    @property
    def time_spent_idle(self) -> int:
        """Check the idle time of this object (in nanos)"""
        if self.last_idle_start is None:
            return 0

        now = time.monotonic_ns()
        return now - self.last_idle_start

    def __str__(self):
        return f"[Connection {self._id}]"

    # The following comparison functions check the "freshness"
    # of a connection. Our logic is as follows: a connection is "fresher"
    # than another if:
    # - it has fewer clients connected
    # - it's been idle longer
    def __gt__(self, other):
        if self.current_client_count == other.current_client_count:
            return self.time_spent_idle < other.time_spent_idle
        return self.current_client_count > other.current_client_count

    def __gte__(self, other):
        if self.current_client_count == other.current_client_count:
            return self.time_spent_idle <= other.time_spent_idle
        return self.current_client_count >= other.current_client_count

    def __eq__(self, other):
        return (
            self.is_ready == other.is_ready
            and self.current_client_count == other.current_client_count
            and self.time_spent_idle == other.time_spent_idle
        )

    def __lt__(self, other):
        if self.current_client_count == other.current_client_count:
            return self.time_spent_idle > other.time_spent_idle
        return self.current_client_count < other.current_client_count

    def __lte__(self, other):
        if self.current_client_count <= other.current_client_count:
            return self.time_spent_idle >= other.time_spent_idle
        return self.current_client_count <= other.current_client_count

    async def checkout(self) -> AbstractConnection:
        """
        This function has the important job of keeping
        track of `last_idle_start` and making sure a connection has been
        established and that it is ready.

        Must be followed by checkin!
        """
        # Bookkeeping: we want to know how long it takes to acquire a connection
        now = time.monotonic_ns()

        # We use a semaphore to manage client limits
        await self.client_limiter.acquire()

        if self.expired and self.current_client_count == 1:
            logger.debug(f"{self} Retiring Connection past its lifespan")
            # Question: can it be closed because one of our clients yielded
            # its await point? In other words, can it be closed out from under a client?
            # self.current_client_count == 1 *should* mean this is the only task!
            await self.close()

        if not self._connection:
            self._connection = await self.create()
            # Make sure connection is ready
            # one thing we could do here is yield the connection and set our event after
            # the *first* successful usage, but defining that success is tougher...?
            await self.check_readiness()

        self.last_idle_start = None

        # We do not want to use locks here because it creates a lot of lock contention,
        # We *only* need to wait for the first successful connection to indicate readiness
        await self._ready.wait()

        # Debug timings to reveal the extent of lock contention
        logger.debug(
            f"{self} available in {time.monotonic_ns()-now}ns "
            f"semaphore state {repr(self.client_limiter)} "
            f"Active client count: {self.current_client_count}"
        )
        return self._connection

    async def checkin(self):
        """Called after a connection has been used"""
        # Release the client limit semaphore!
        try:
            self.client_limiter.release()
        except RuntimeError:
            pass

        logger.debug(f"{self}.current_client_count is now {self.current_client_count}")

        # we only consider idle time to start when *no* clients are connected
        if self.current_client_count == 0:
            logger.debug(f"{self} is now idle")
            self.last_idle_start = time.monotonic_ns()

            # Check if TTL exceeded for this connection
            if self.max_lifespan_ns is not None and self.expired:
                await self.close()

    @asynccontextmanager
    async def acquire(self, timeout=10) -> AsyncGenerator[AbstractConnection | None, None]:
        """Acquire a connection with a timeout"""
        acquired_conn = None
        async with create_task_group():
            with move_on_after(timeout) as scope:
                acquired_conn = await self.checkout()

        # If this were nested under `create_task_group` then any exceptions
        # get thrown under `BaseExceptionGroup`, which is surprising for clients.
        # See: https://github.com/agronholm/anyio/issues/141
        if not scope.cancelled_caught and acquired_conn:
            try:
                yield acquired_conn
            finally:
                await self.checkin()
        else:
            await self.checkin()
            yield None

    async def create(self) -> AbstractConnection:
        """Establishes the connection or reuses existing if already created."""
        if self._connection:
            return self._connection

        # We use a lock on *opening* a connection
        async with self._open_close_lock:
            logger.debug(f"{self} Creating a new connection")
            self._connection = await self._connector.create()
            # Check if we need to expire connections based on lifespan
            if self.max_lifespan_ns is not None:
                self.connection_created_ts = time.monotonic_ns()
            return self._connection

    @property
    def is_ready(self) -> bool:
        """Proxy for whether our readiness Event has been set."""
        return self._ready.is_set()

    async def check_readiness(self) -> None:
        """Indicates when ready by waiting for the connector to signal"""
        if self._ready.is_set():
            return None

        # We use a lock when making sure the connection is ready
        # Our goal is to set readiness Event once for one client.
        if self._connection:
            async with self._open_close_lock:
                logger.debug(f"{self} Setting readiness")
                is_ready = await self._connector.ready(self._connection)
                if is_ready:
                    self._ready.set()
                else:
                    raise ConnectionFailed("Failed readying connection")

    async def close(self) -> None:
        """Closes the connection"""
        if self._connection is None:
            return None

        # We use a lock on *closing* a connection
        async with self._open_close_lock:
            logger.debug(f"{self} Closing the Connection")
            try:
                await self._connection.close()
            except Exception:
                pass

            self._connection = None
            self._ready = anyio.Event()
            self.last_idle_start = None
            if self.max_lifespan_ns is not None:
                self.connection_created_ts = None


class ConnectionPool:
    """
    Our goal here is to allow many clients to share connections,
    but to expire them when they've reached their idle time limits.

    Most clients can call this with the default values below.

    Args:
      connector:
        An instance of an AbstractConnector for creating connections.
      client_limit:
        The max clients allowed _per_ connection (default: 100).
      max_size:
        The max size for the connection pool or max connections held (default: 10).
      max_idle_seconds:
        Maximum duration allowed for an idle connection before recylcing it.
      max_lifespan_seconds:
        Optional setting which controls how long a connection live before recycling.
    """

    def __init__(
        self,
        connector: AbstractorConnector,
        client_limit: int = DEFAULT_SHARED_TRANSPORT_CLIENT_LIMIT,
        max_size: int = DEFAULT_MAX_SIZE,
        max_idle_seconds: int = DEFAULT_CONNECTION_MAX_IDLE_SECONDS,
        max_lifespan_seconds: int | None = None,
    ):
        # Each shared connection allows up to this many connections
        self.client_limit = client_limit
        # Pool's max size
        self.max_size = max_size
        if self.max_size < 1:
            raise ValueError("max_size must a postive integer")
        self.connector = connector

        # A pool is just a heap of connection-managing things
        # All synchronization primitives are in the connections
        self._pool = [
            SharedTransportConnection(
                self.connector,
                client_limit=self.client_limit,
                max_idle_seconds=max_idle_seconds,
                max_lifespan_seconds=max_lifespan_seconds,
            )
            for _ in range(self.max_size)
        ]
        heapq.heapify(self._pool)
        self.max_lifespan_seconds = max_lifespan_seconds

    @asynccontextmanager
    async def get(
        self,
        timeout=10.0,
    ) -> AsyncGenerator[AbstractConnection, None]:
        """
        Pull out an idle connection.

        The binary heap allows us to always pull out the *youngest*
        connection, which is the one most likely to connect without issues.
        This relies on the less-than/greater-than implementation above.

        Throws: `ConnectionsExhausted` if too many connections opened.
        """
        connection_reached = False
        total_time = 0
        # We'll loop through roughly half the pool to find a candidate
        # We add one in case it's zero.
        conn_check_n = (self.max_size // 2) + 1
        while not connection_reached and total_time < timeout:
            for _conn in heapq.nsmallest(conn_check_n, self._pool):
                if _conn.available:
                    async with _conn.acquire(timeout=timeout) as conn:
                        if conn is not None:
                            yield conn
                            connection_reached = True
                            break

            await anyio.sleep(0.01)
            total_time += 0.01

        if connection_reached:
            heapq.heapify(self._pool)
        else:
            raise ConnectionsExhausted(
                "No connections available: consider using a larger value for `client_limit`"
            )

    async def closeall(self) -> None:
        """Close all connections"""
        async with create_task_group() as tg:
            for conn in self._pool:
                tg.start_soon(conn.close)

    @property
    def ready_connection_count(self):
        return sum(1 for conn in self._pool if conn)

    async def expire_conn(self, connection: AbstractConnection) -> None:
        """
        Expire a connection.
        Because we yield AbstractConnections while our pool is SharedTransportConnections,
        we need to give clients a way to look up a connection and expire it directly.
        """
        for conn in self._pool:
            if conn.eq(connection):
                await conn.close()
                break
        heapq.heapify(self._pool)
        return None
