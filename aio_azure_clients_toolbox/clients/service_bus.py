"""
service_bus.py

Wrapper class around a `ServiceBusClient` which allows sending messages or
subscribing to a queue.
"""

import datetime
import logging
import traceback

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

# Actual time limit: 240s
SERVICE_BUS_SEND_TTL_SECONDS = 200
logger = logging.getLogger(__name__)


class AzureServiceBus:
    """
    Basic AzureServiceBus client without connection pooling.

    For connection pooling see `ManagedAzureServiceBus` below.
    """

    def __init__(
        self,
        service_bus_namespace_url: str,
        service_bus_queue_name: str,
        credential: DefaultAzureCredential,
    ):
        self.namespace_url = service_bus_namespace_url
        self.queue_name = service_bus_queue_name
        self.credential = credential
        self._client: ServiceBusClient | None = None
        self._receiver_client: ServiceBusReceiver | None = None
        self._sender_client: ServiceBusSender | None = None

    def _validate_access_settings(self):
        if not all((self.namespace_url, self.queue_name, self.credential)):
            raise ValueError("Invalid configuration for AzureServiceBus")
        return None

    @property
    def client(self):
        if self._client is None:
            self._validate_access_settings()
            self._client = ServiceBusClient(self.namespace_url, self.credential)
        return self._client

    def get_receiver(self) -> ServiceBusReceiver:
        if self._receiver_client is not None:
            return self._receiver_client

        self._receiver_client = self.client.get_queue_receiver(
            queue_name=self.queue_name, receive_mode=ServiceBusReceiveMode.PEEK_LOCK
        )
        return self._receiver_client

    def get_sender(self) -> ServiceBusSender:
        if self._sender_client is not None:
            return self._sender_client

        self._sender_client = self.client.get_queue_sender(queue_name=self.queue_name)
        return self._sender_client

    async def close(self):
        if self._receiver_client is not None:
            await self._receiver_client.close()
            self._receiver_client = None

        if self._sender_client is not None:
            await self._sender_client.close()
            self._sender_client = None

        if self._client is not None:
            await self._client.close()
            self._client = None

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
      credential:
        An async DefaultAzureCredential which may be used to authenticate to the container.
      client_limit:
        Client limit per connection (default: 100).
      max_size:
        Connection pool size (default: 10).
      max_idle_seconds:
        Maximum duration allowed for an idle connection before recylcing it.
      ready_message:
        A string representing the first "ready" message sent to establish connection.
    """

    def __init__(
        self,
        service_bus_namespace_url: str,
        service_bus_queue_name: str,
        credential: DefaultAzureCredential,
        client_limit: int = connection_pooling.DEFAULT_SHARED_TRANSPORT_CLIENT_LIMIT,
        max_size: int = connection_pooling.DEFAULT_MAX_SIZE,
        max_idle_seconds: int = SERVICE_BUS_SEND_TTL_SECONDS,
        ready_message: str = "Connection established",
    ):
        self.service_bus_namespace_url = service_bus_namespace_url
        self.service_bus_queue_name = service_bus_queue_name
        self.credential = credential
        self.pool = connection_pooling.ConnectionPool(
            self,
            client_limit=client_limit,
            max_size=max_size,
            max_idle_seconds=max_idle_seconds,
        )
        self.ready_message = ready_message

    def get_sender(self) -> ServiceBusSender:
        client = AzureServiceBus(
            self.service_bus_namespace_url,
            self.service_bus_queue_name,
            self.credential,
        )
        return client.get_sender()

    async def create(self) -> ServiceBusSender:
        """Creates a new connection for our pool"""
        return self.get_sender()

    def get_receiver(self) -> ServiceBusReceiver:
        """
        Proxy for AzureServiceBus.get_receiver. Here
        for consistency with above class.
        """
        client = AzureServiceBus(
            self.service_bus_namespace_url,
            self.service_bus_queue_name,
            self.credential,
        )
        return client.get_receiver()

    async def close(self):
        """Closes all connections in our pool"""
        await self.pool.closeall()
        try:
            await self.credential.close()
        except Exception as exc:
            logger.warning(f"Credential close failed with {exc}")

    @connection_pooling.send_time_deco(logger, "ServiceBus.ready")
    async def ready(self, conn: ServiceBusSender) -> bool:
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
        async with self.pool.get() as conn:
            try:
                await conn.schedule_messages(message, scheduled_time_utc)
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
