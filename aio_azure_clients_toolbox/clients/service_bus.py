"""
service_bus.py

Wrapper class around a `ServiceBusClient` which allows sending messages or
subscribing to a queue.
"""

import datetime
import logging
import traceback
from typing import cast

from azure.core import exceptions
from azure.identity.aio import DefaultAzureCredential
from azure.servicebus import ServiceBusMessage, ServiceBusReceiveMode
from azure.servicebus.aio import ServiceBusClient, ServiceBusReceiver, ServiceBusSender
from azure.servicebus.exceptions import (
    ServiceBusAuthenticationError,
    ServiceBusAuthorizationError,
    ServiceBusCommunicationError,
    ServiceBusConnectionError,
    ServiceBusError,
)

from aio_azure_clients_toolbox import connection_pooling

from .types import CredentialFactory

# Actual time limit: 240s
SERVICE_BUS_SEND_TTL_SECONDS = 200
logger = logging.getLogger(__name__)


class SendClientCloseWrapper:
    """
    Wrapper class for a ServiceBusSender which ensures that the sender is closed
    after use.
    """

    def __init__(self, sender: ServiceBusSender, credential: DefaultAzureCredential):
        self._sender = sender
        self._credential = credential

    def __getattr__(self, name: str):
        return getattr(self._sender, name)

    async def close(self):
        await self._sender.close()
        await self._credential.close()


class AzureServiceBus:
    """
    Basic AzureServiceBus client without connection pooling.

    For connection pooling see `ManagedAzureServiceBus` below.
    """

    def __init__(
        self,
        service_bus_namespace_url: str,
        service_bus_queue_name: str,
        credential_factory: CredentialFactory,
        socket_timeout: float = 1,  ## Value in seconds. Azure default value is 0.2s
    ):
        self.namespace_url = service_bus_namespace_url
        self.queue_name = service_bus_queue_name
        if not callable(credential_factory):
            raise ValueError(
                "credential_factory must be a callable returning a credential"
            )
        self.credential_factory = credential_factory
        self._receiver_client: ServiceBusReceiver | None = None
        self._receiver_credential: DefaultAzureCredential | None = None
        self._sender_client: SendClientCloseWrapper | None = None
        self._socket_timeout: float = socket_timeout

    def _validate_access_settings(self):
        if not all((self.namespace_url, self.queue_name)):
            raise ValueError("Invalid configuration for AzureServiceBus")
        return None

    def get_receiver(self) -> ServiceBusReceiver:
        if self._receiver_client is not None:
            return self._receiver_client

        credential = self.credential_factory()
        self._receiver_credential = credential
        sbc = ServiceBusClient(self.namespace_url, credential)
        self._receiver_client = sbc.get_queue_receiver(
            queue_name=self.queue_name,
            receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
            socket_timeout=self._socket_timeout,
        )
        return self._receiver_client

    def get_sender(self) -> SendClientCloseWrapper:
        if self._sender_client is not None:
            return self._sender_client

        credential = self.credential_factory()
        sbc = ServiceBusClient(self.namespace_url, credential)

        sender_client = sbc.get_queue_sender(queue_name=self.queue_name, socket_timeout=self._socket_timeout)
        self._sender_client = SendClientCloseWrapper(sender_client, credential)
        return self._sender_client

    async def close(self):
        if self._receiver_client is not None:
            await self._receiver_client.close()
            self._receiver_client = None
        if self._receiver_credential is not None:
            await self._receiver_credential.close()
            self._receiver_credential = None

        if self._sender_client is not None:
            await self._sender_client.close()
            self._sender_client = None

    async def send_message(self, msg: str, delay: int = 0):
        message = ServiceBusMessage(msg)
        now = datetime.datetime.now(tz=datetime.UTC)
        scheduled_time_utc = now + datetime.timedelta(seconds=delay)
        sender = self.get_sender()
        await sender.schedule_messages(message, scheduled_time_utc)


class ManagedAzureServiceBusSender(connection_pooling.AbstractorConnector):
    """Azure ServiceBus Sender client with connnection pooling built in.

    Args:
      service_bus_namespace_url:
        String representing the ServiceBus namespace URL.
      service_bus_queue_name:
        Queue name (the "topic").
      credential_factory:
        A callable that returns an async DefaultAzureCredential which may be used to authenticate to the container.
      client_limit:
        Client limit per connection (default: 100).
      max_size:
        Connection pool size (default: 10).
      max_idle_seconds:
        Maximum duration allowed for an idle connection before recylcing it.
      max_lifespan_seconds:
        Optional setting which controls how long a connection lives before recycling.
      pool_connection_create_timeout:
       Timeout for creating a connection in the pool (default: 10 seconds).
      pool_get_timeout:
        Timeout for getting a connection from the pool (default: 60 seconds).
      ready_message:
        A string or bytes representing the first "ready" message sent to establish connection.
    """

    def __init__(
        self,
        service_bus_namespace_url: str,
        service_bus_queue_name: str,
        credential_factory: CredentialFactory,
        client_limit: int = connection_pooling.DEFAULT_SHARED_TRANSPORT_CLIENT_LIMIT,
        max_size: int = connection_pooling.DEFAULT_MAX_SIZE,
        max_idle_seconds: int = SERVICE_BUS_SEND_TTL_SECONDS,
        max_lifespan_seconds: int | None = None,
        ready_message: str | bytes = "Connection established",
        pool_connection_create_timeout: int = 10,
        pool_get_timeout: int = 60,
    ):
        self.service_bus_namespace_url = service_bus_namespace_url
        self.service_bus_queue_name = service_bus_queue_name
        if not callable(credential_factory):
            raise ValueError(
                "credential_factory must be a callable returning a credential"
            )

        self.credential_factory = credential_factory

        self.pool = connection_pooling.ConnectionPool(
            self,
            client_limit=client_limit,
            max_size=max_size,
            max_idle_seconds=max_idle_seconds,
            max_lifespan_seconds=max_lifespan_seconds,
        )
        if not isinstance(ready_message, (str, bytes)):
            raise ValueError("ready_message must be a string or bytes")
        self.ready_message = ready_message

        self.pool_kwargs = {
            "timeout": pool_get_timeout,
            "acquire_timeout": pool_connection_create_timeout,
        }

    def get_sender(self) -> SendClientCloseWrapper:
        client = AzureServiceBus(
            self.service_bus_namespace_url,
            self.service_bus_queue_name,
            self.credential_factory,
        )
        return client.get_sender()

    async def create(self) -> connection_pooling.AbstractConnection:
        """Creates a new connection for our pool"""
        return cast(connection_pooling.AbstractConnection, self.get_sender())

    def get_receiver(self) -> ServiceBusReceiver:
        """
        Proxy for AzureServiceBus.get_receiver. Here
        for consistency with above class.
        """
        client = AzureServiceBus(
            self.service_bus_namespace_url,
            self.service_bus_queue_name,
            self.credential_factory,
        )
        return client.get_receiver()

    async def close(self):
        """Closes all connections in our pool"""
        await self.pool.closeall()

    @connection_pooling.send_time_deco(logger, "ServiceBus.ready")
    async def ready(self, conn: SendClientCloseWrapper) -> bool:
        """Establishes readiness for a new connection"""
        message = ServiceBusMessage(self.ready_message)
        now = datetime.datetime.now(tz=datetime.UTC)
        attempts = 2
        while attempts > 0:
            try:
                await conn.schedule_messages(message, now)
                return True
            except (ServiceBusAuthorizationError, ServiceBusAuthenticationError):
                # We do not believe these will improve with repeated tries
                logger.error(
                    "ServiceBus Authorization or Authentication error. Not ready."
                )
                raise
            except (AttributeError, ServiceBusError, exceptions.AzureError):
                logger.warning(
                    f"ServiceBus readiness check #{3 - attempts} failed; trying again."
                )
                logger.error(f"{traceback.format_exc()}")
                attempts -= 1

        logger.error("ServiceBus readiness check failed. Not ready.")
        return False

    @connection_pooling.send_time_deco(logger, "ServiceBus.send_message")
    async def send_message(self, msg: str, delay: int = 0):
        message = ServiceBusMessage(msg)
        now = datetime.datetime.now(tz=datetime.UTC)
        scheduled_time_utc = now + datetime.timedelta(seconds=delay)
        async with self.pool.get(**self.pool_kwargs) as conn:
            try:
                await cast(SendClientCloseWrapper, conn).schedule_messages(
                    message, scheduled_time_utc
                )
            except (
                ServiceBusCommunicationError,
                ServiceBusAuthorizationError,
                ServiceBusAuthenticationError,
                ServiceBusConnectionError,
            ):
                logger.exception(
                    f"ServiceBus.send_message failed. Expiring connection: {traceback.format_exc()}"
                )
                await self.pool.expire_conn(conn)
                raise
