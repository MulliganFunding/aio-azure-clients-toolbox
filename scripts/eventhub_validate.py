"""
  This script is a means to validate our connection-pooling
  implementation for Eventhub producer clients.

Example:

  ❯ poetry run python -m scripts.eventhub_validate \
        -u "some-eventhub-namespace.servicebus.windows.net" \
        -n "some_eventhub_name"
"""

import asyncio
import logging
import traceback

from anyio import sleep
from azure.eventhub import EventData, TransportType
from azure.eventhub.aio import EventHubConsumerClient
from azure.identity.aio import DefaultAzureCredential
from rich.logging import RichHandler

from aio_azure_clients_toolbox import connection_pooling
from aio_azure_clients_toolbox.clients import eventhub


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
for logname in (
    "aio_azure_clients_toolbox.connection_pooling",
    "aio_azure_clients_toolbox.clients.eventhub",
):

    cpool_logger = logging.getLogger(logname)
    cpool_logger.setLevel(logging.DEBUG)


FORMAT = "%(name)s - %(message)s"
logging.basicConfig(format=FORMAT, datefmt="[%X]", handlers=[RichHandler()])

servicebus_logger = logging.getLogger("azure.eventhub")
servicebus_logger.setLevel(logging.WARNING)
identity_logger = logging.getLogger("azure.identity")
identity_logger.setLevel(logging.WARNING)


# # # # # # # # # # # # # # # # # #
# Eventhub consumer debugging function
async def on_partition_initialize(partition_context):
    msg = (
        f"Hub: {partition_context.eventhub_name} "
        f"Partition: {partition_context.partition_id} "
        f"has been initialized."
    )

    logger.warning(
        msg,
        partition_id=partition_context.partition_id,
        callback="on_partition_initialize",
    )


async def on_partition_close(partition_context, reason):
    msg = f"Partition {partition_context.partition_id} closed"
    logger.warning(
        msg,
        event_hub=partition_context.eventhub_name,
        partition_id=partition_context.partition_id,
        reason=reason,
        callback="on_partition_close",
    )


async def on_partition_error(partition_context, error):
    if partition_context:
        msg = (
            f"An exception: {partition_context.partition_id} "
            f"occurred during receiving from Partition: {error}."
        )

        # Make this a warning to cut down on noise
        logger.error(
            msg,
            event_hub=partition_context.eventhub_name,
            partition_id=partition_context.partition_id,
            callback="on_partition_error",
        )
    else:
        msg = f"An exception: {error} occurred during the load balance process."
        logger.error(msg)


async def on_event(
    partition_context,
    event: EventData,
):
    """
    Log the received messages
    """
    msg = event.body_as_str()
    logger.info(f"[{event.sequence_number}] Received message `{msg}`")


async def main(
    eventhub_namespace: str,
    eventhub_name: str,
    exclude_msi_credential: bool = False,
):
    credential = DefaultAzureCredential(
        exclude_managed_identity_credential=exclude_msi_credential
    )
    pool_size = 3
    sender = eventhub.ManagedAzureEventhubProducer(
        eventhub_namespace,
        eventhub_name,
        credential,
        client_limit=5,  # For debugging!
        max_idle_seconds=5,
        max_size=pool_size,
    )
    tasks = []
    message_count = connection_pooling.DEFAULT_MAX_SIZE * 2
    for n in range(message_count):
        tasks.append(sender.send_event(f"Test-message {n}", partition_key="1"))

    results = await asyncio.gather(*tasks)

    logger.debug("Sleeping for 1s")
    await sleep(1)

    await asyncio.gather(
        sender.send_event("Test-message post-sleep 1s msg1", partition_key="1"),
        sender.send_event("Test-message post-sleep 1s msg2", partition_key="1"),
    )

    # sleep long enough for connections to be closed
    logger.debug("Sleeping for 5s")
    await sleep(5)

    await asyncio.gather(
        sender.send_event("Test-message post-sleep 5s msg1", partition_key="1"),
        sender.send_event("Test-message post-sleep 5s msg2", partition_key="1"),
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
    receiver_client = EventHubConsumerClient(
        fully_qualified_namespace=eventhub_namespace,
        eventhub_name=eventhub_name,
        consumer_group="local-dev",
        credential=credential,
        on_error=on_partition_error,
        on_partition_close=on_partition_close,
        on_partition_initialize=on_partition_initialize,
        transport_type=TransportType.AmqpOverWebsocket,
    )
    async with receiver_client:
        logger.warning("Running read-message loop. Press CTRL+C to terminate")
        await receiver_client.receive(on_event=on_event, starting_position="-1")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser("service-bus-validate")
    parser.add_argument("--use-msi", action="store_true")
    parser.add_argument("--namespace-url", "-u", required=True)
    parser.add_argument("--name", "-n", required=True)

    args = parser.parse_args()
    asyncio.run(
        main(args.namespace_url, args.name, exclude_msi_credential=not args.use_msi)
    )
