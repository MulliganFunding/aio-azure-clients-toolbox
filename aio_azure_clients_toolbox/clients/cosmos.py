import enum
import logging
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass

from azure.core import MatchConditions
from azure.cosmos import exceptions
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.identity.aio import DefaultAzureCredential

from aio_azure_clients_toolbox import connection_pooling

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
CLIENT_TTL_SECONDS_DEFAULT = 60
CLIENT_IDLE_SECONDS_DEFAULT = 30


@enum.unique
class PatchOp(str, enum.Enum):
    """
    Following is an example of patch operations:
        operations = [
            {"op": "add", "path": "/favorite_color", "value": "red"},
            {"op": "remove", "path": "/ttl"},
            {"op": "replace", "path": "/tax_amount", "value": 14},
            {"op": "set", "path": "/items/0/discount", "value": 20.0512},
            {"op": "incr", "path": "/total_due", "value": 5},
            {"op": "move", "from": "/freight", "path": "/service_addition"}
        ]
    Note: `set` Set operation adds a property if it doesn't already exist
    (except if there was an Array ) while `replace` operation fails if
    the property doesn't exist.
    """

    Add = "add"
    Remove = "remove"
    Replace = "replace"
    Set = "set"
    Incr = "incr"
    Move = "move"

    def as_op(self, path: str, value: str):
        """These variables make sense for all but Move"""
        if self is PatchOp.Move:
            return {"op": self.value, "from": path, "path": value}

        return {"op": self.value, "path": path, "value": value}


@dataclass
class Operation:
    """For turning patch Operations into instructions Cosmos understands"""

    op: PatchOp
    path: str
    value: str

    def as_op(self):
        return self.op.as_op(self.path, self.value)


class ConnectionManager:
    def __init__(
        self,
        endpoint: str,
        dbname: str,
        container_name: str,
        credential: DefaultAzureCredential,
        lifespan_enabled: bool = False,
        cosmos_client_ttl_seconds: int = CLIENT_TTL_SECONDS_DEFAULT,
    ):
        self.endpoint = endpoint
        self.credential = credential
        self.db_name = dbname
        self.container_name = container_name
        self.client_lifespan_seconds = cosmos_client_ttl_seconds
        self.lifespan_enabled = lifespan_enabled
        if self.lifespan_enabled and not self.client_lifespan_seconds:
            raise ValueError(f"Bad value for client lifespan {self.client_lifespan_seconds}")
        if self.lifespan_enabled and not isinstance(self.client_lifespan_seconds, int):
            raise ValueError(f"Bad value for client lifespan {self.client_lifespan_seconds}")
        if self.lifespan_enabled and self.client_lifespan_seconds < 0:
            raise ValueError(f"Client lifespan must be positive: {self.client_lifespan_seconds}")

        # These are clients that must be managed manually
        self._client = None
        self._database = None
        self._container = None
        # This is a call to time.monotonic() which can't go backwards
        # and represents *seconds*
        self._client_lifespan_started = None

    @property
    def is_container_closed(self):
        """Check if *any* attributes set to None"""
        return any(cli is None for cli in (self._client, self._database, self._client))

    @property
    def should_recycle_container(self) -> bool:
        if self.is_container_closed:
            return True

        if not self.lifespan_enabled:
            return False

        if self._client_lifespan_started is None:
            return True
        now = time.monotonic()
        return (now - self._client_lifespan_started) > self.client_lifespan_seconds

    async def recycle_container(self):
        if self._client is not None:
            await self._client.close()
        try:
            await self.credential.close()
        except Exception as exc:
            logger.warning("Error closing credential: %s", exc)

        self._client = None
        self._database = None
        self._container = None

    async def get_container_client(self):
        """
        This method will return a container client.

        Because making connections is expensive, we'd like to preserve them
        for a while.
        """
        if self.should_recycle_container:
            logger.info("Recycling Cosmos client")
            await self.recycle_container()

        if self.is_container_closed:
            logger.info("Creating new Cosmos client")
            self._client = CosmosClient(self.endpoint, credential=self.credential)
            self._database = self._client.get_database_client(self.db_name)
            self._container = self._database.get_container_client(self.container_name)
            self._client_lifespan_started = time.monotonic()

        return self._container

    async def __aenter__(self):
        """
        Here we manage our connection:
        - if still alive, we return
        - if needing to recyle, we recyle and create
        - if not created, we create
        """
        try:
            return await self.get_container_client()
        except exceptions.CosmosHttpResponseError as exc:
            raise ValueError("Container client cannot be constructed") from exc

    async def __aexit__(self, exc_type, exc, tb):
        """Close connection if needing to recycle"""
        if self.should_recycle_container:
            await self.recycle_container()


class Cosmos:
    """Applications can subclass this class to interact with their container"""

    MatchConditions = MatchConditions

    def __init__(
        self,
        endpoint: str,
        dbname: str,
        container_name: str,
        credential: DefaultAzureCredential,
        cosmos_client_ttl_seconds: int = CLIENT_TTL_SECONDS_DEFAULT,
    ):
        self.container_name = container_name
        self.connection_manager = ConnectionManager(
            endpoint,
            dbname,
            container_name,
            credential,
            lifespan_enabled=False,
            cosmos_client_ttl_seconds=cosmos_client_ttl_seconds,
        )

    async def close(self):
        await self.connection_manager.recycle_container()

    @asynccontextmanager
    async def get_container_client(self):
        """
        This async context manager will yield a container client.

        Because making connections is expensive, we'd like to preserve them
        for a while.
        """
        # If already closed throws
        # AttributeError: 'NoneType' object has no attribute '__aenter__'
        async with self.connection_manager as client:
            yield client


class SimpleCosmos:
    """Applications can subclass this class to keep async connections open"""

    MatchConditions = MatchConditions

    def __init__(
        self,
        endpoint: str,
        dbname: str,
        container_name: str,
        credential: DefaultAzureCredential,
    ):
        self.endpoint = endpoint
        self.credential = credential
        self.db_name = dbname
        self.container_name = container_name
        # when these connecttions gets created they will be parked here
        self._container = None
        self._client = None
        self._db = None

    def __getattr__(self, key: str):
        if self._container is None:
            raise AttributeError("Container client not constructed")
        return getattr(self._container, key)

    async def get_container_client(self) -> ContainerProxy:
        """
        This method will return a container client.
        """
        self._client = CosmosClient(self.endpoint, credential=self.credential)
        self._db = self._client.get_database_client(self.db_name)
        self._container = self._db.get_container_client(self.container_name)
        return self

    async def close(self):
        if self._client is not None:
            await self._client.close()

        self._container = None
        self._db = None
        self._client = None


class ManagedCosmos(connection_pooling.AbstractorConnector):
    """
    "Managed" version of the above: uses a connection pool to keep connections
    alive.

    Applications can subclass this class to interact with their container

    Args:
      endpont:
        A string URL of the Cosmos server.
      dbname:
        Cosmos database name.
      container_name:
        Cosmos container name.
      credential:
        An async DefaultAzureCredential which may be used to authenticate to the container.
      client_limit:
        Client limit per connection (default: 100).
      max_size:
        Connection pool size (default: 10).
      max_idle_seconds:
        Maximum duration allowed for an idle connection before recylcing it.
      max_lifespan_seconds:
        Optional setting which controls how long a connection live before recycling.
    """

    MatchConditions = MatchConditions

    def __init__(
        self,
        endpoint: str,
        dbname: str,
        container_name: str,
        credential: DefaultAzureCredential,
        client_limit: int = connection_pooling.DEFAULT_SHARED_TRANSPORT_CLIENT_LIMIT,
        max_size: int = connection_pooling.DEFAULT_MAX_SIZE,
        max_idle_seconds: int = CLIENT_IDLE_SECONDS_DEFAULT,
        max_lifespan_seconds: int = CLIENT_TTL_SECONDS_DEFAULT,
    ):
        self.endpoint = endpoint
        self.dbname = dbname
        self.container_name = container_name
        self.credential = credential
        self.max_idle_seconds = max_idle_seconds
        self.pool = connection_pooling.ConnectionPool(
            self,
            client_limit=client_limit,
            max_size=max_size,
            max_idle_seconds=max_idle_seconds,
            max_lifespan_seconds=max_lifespan_seconds,
        )

    async def create(self):
        """Creates a new connection for our pool"""
        client = SimpleCosmos(
            self.endpoint,
            self.dbname,
            self.container_name,
            self.credential,
        )
        await client.get_container_client()
        return client

    @connection_pooling.send_time_deco(logger, "Cosmos.ready")
    async def ready(self, container: ContainerProxy) -> bool:
        attempts = 2
        while attempts > 0:
            try:
                await container.read()
                return True
            except exceptions.CosmosHttpResponseError:
                logger.warning(
                    f"Cosmos readiness check #{3 - attempts} failed with {traceback.format_exc()}. "
                    "trying again."
                )
                logger.error(f"{traceback.format_exc()}")
                attempts -= 1

        logger.error("Cosmos readiness check failed. Not ready.")
        return False

    async def close(self):
        """Closes all connections in our pool"""
        await self.pool.closeall()
        try:
            await self.credential.close()
        except Exception as exc:
            logger.warning(f"Credential close failed with {exc}")

    @asynccontextmanager
    async def get_container_client(self):
        """
        This async context manager will yield a container client.

        Because making connections is expensive, we'd like to preserve them
        for a while.
        """
        async with self.pool.get() as conn:
            yield conn
