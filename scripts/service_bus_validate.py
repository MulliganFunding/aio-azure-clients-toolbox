"""
  This script is a means to validate our connection-pooling
  implementation for service-bus send clients.

  Example:

  ❯ poetry run python -m scripts.service_bus_validate \
        -u "some-service-bus.servicebus.windows.net" \
        -q "some_queue_name"
"""

import asyncio
import logging
import traceback

from anyio import sleep
from azure.identity.aio import DefaultAzureCredential
from rich.logging import RichHandler

from aio_azure_clients_toolbox import connection_pooling
from aio_azure_clients_toolbox.clients import service_bus


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
for logname in (
    "aio_azure_clients_toolbox.connection_pooling",
    "aio_azure_clients_toolbox.clients.service_bus",
):

    cpool_logger = logging.getLogger(logname)
    cpool_logger.setLevel(logging.DEBUG)


FORMAT = "%(name)s - %(message)s"
logging.basicConfig(format=FORMAT, datefmt="[%X]", handlers=[RichHandler()])

servicebus_logger = logging.getLogger("azure.servicebus")
servicebus_logger.setLevel(logging.WARNING)
identity_logger = logging.getLogger("azure.identity")
identity_logger.setLevel(logging.INFO)


async def main(
    service_bus_namespace_url: str,
    service_bus_queue_name: str,
    exclude_msi_credential: bool = False,
):
    credential = DefaultAzureCredential(
        exclude_managed_identity_credential=exclude_msi_credential
    )
    pool_size = 3
    sender = service_bus.ManagedAzureServiceBusSender(
        service_bus_namespace_url,
        service_bus_queue_name,
        credential,
        client_limit=5,  # For debugging!
        max_idle_seconds=5,
        max_size=pool_size,
    )
    tasks = []
    message_count = connection_pooling.DEFAULT_MAX_SIZE * 2
    for n in range(message_count):
        tasks.append(sender.send_message(f"Test-message {n}"))

    results = await asyncio.gather(*tasks)

    logger.debug("Sleeping for 1s")
    await sleep(1)

    await asyncio.gather(
        sender.send_message("Test-message post-sleep 1s msg1"),
        sender.send_message("Test-message post-sleep 1s msg2"),
    )

    # sleep long enough for connections to be closed
    logger.debug("Sleeping for 5s")
    await sleep(5)
    # We expect connection established_messages to be this many
    connect_est_msg_count = pool_size + 2  # 2 reconnects!

    await asyncio.gather(
        sender.send_message("Test-message post-sleep 5s msg1"),
        sender.send_message("Test-message post-sleep 5s msg2"),
    )
    message_count += 4

    exception_count = 0
    for result in results:
        if isinstance(result, Exception):
            exception_count += 1
            logger.info(f"Hit exception {traceback.format_exception(result)}")

    logger.info(f"Total exception count {exception_count}")

    logger.info("Closing all connections")
    await sender.close()

    logger.info("Checking submitted messages")
    receiver_client = service_bus.AzureServiceBus(
        service_bus_namespace_url, service_bus_queue_name, credential
    )

    received_message_count = 0
    connect_est_message_recv_count = 0
    async with receiver_client.get_receiver() as receiver:
        async for msg in receiver:
            logger.info(f"Received message `{msg}`")
            await receiver.complete_message(msg)
            received_message_count += 1
            if str(msg) == "Connection established":
                connect_est_message_recv_count += 1
            # We expect 5 "connection established" messages
            if received_message_count >= message_count + connect_est_msg_count:
                break

    if connect_est_message_recv_count == connect_est_msg_count:
        logger.info("Confirmed expected number of connection established messages")
    else:
        logger.warning(
            f"Unexpected number of `Connection Established` messages={connect_est_message_recv_count}"
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser("service-bus-validate")
    parser.add_argument("--use-msi", action="store_true")
    parser.add_argument("--namespace-url", "-u", required=True)
    parser.add_argument("--queue", "-q", required=True)

    args = parser.parse_args()
    asyncio.run(
        main(args.namespace_url, args.queue, exclude_msi_credential=not args.use_msi)
    )
