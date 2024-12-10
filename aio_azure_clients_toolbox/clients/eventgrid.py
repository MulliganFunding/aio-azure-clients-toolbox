from dataclasses import dataclass

from azure.eventgrid import EventGridEvent, EventGridPublisherClient
from azure.eventgrid.aio import EventGridPublisherClient as AsyncEventGridPublisherClient
from azure.identity import DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential


@dataclass
class EventGridTopicConfig:
    """Configuration for one event grid topic subscription"""

    # Name of the topic
    name: str

    # URL for the topic api, e.g. `https://dev-ocr.westus2-1.eventgrid.azure.net/api/events`
    url: str


class EventGridConfig:
    """Configuration for all topics available to a single event grid client"""

    def __init__(self, topic_configs: EventGridTopicConfig | list[EventGridTopicConfig]):
        self.topic_configs = {}

        if isinstance(topic_configs, EventGridTopicConfig):
            topic_configs = [topic_configs]

        for topic_config in topic_configs:
            self.topic_configs[topic_config.name] = topic_config

    def topics(self) -> list[str]:
        """Get list of topic names in this config."""
        return list(self.topic_configs.keys())

    def config(self, topic: str) -> EventGridTopicConfig:
        """Get the config for a topic by name."""
        return self.topic_configs[topic]

    def url(self, topic: str) -> str:
        """Get the URL for a topic."""
        return self.config(topic).url


class EventGridClient:
    """
    A generic eventgrid client

    This generic eventgrid client provides a few nice features on top of the
    native azure python client. Primarily it provides a convenient way to
    configure publishing to multiple topics using a single client.

    Example:

        ```
        topic1 = EventGridTopicConfig("topic1", "https://azure.net/topic1")
        topic2 = EventGridTopicConfig("topic2", "https://azure.net/topic2")

        client_config = EventGridConfig([topic1, topic2])
        managed_identity_credential = DefaultAzureCredential() client =
        EventGridClient(config, credential=credential)
        ```

    The client run asynchronously or synchronously. To run the client async
    provide the `async_credential` arg when creating the client and use the
    asyncmethods, e.g. `client.async_emit_event()`.

        ```
        from azure.identity.aio import DefaultAzureCredential

        credential = DefaultAzureCredential()
        topic = EventGridTopicConfig("topic", "https://azure.net/topic")
        config = EventGridConfig(topic)
        client = EventGridClient(config, async_credential=credential)
        await client.async_emit_event("topic", "ident", {},"event-type", "subject")
        ```

    To run the client synchronously, provide the `credential` arg when
    creating the client and call non-prefixed functions.

        ```
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential()
        topic = EventGridTopicConfig("topic", "https://azure.net/topic")
        config = EventGridConfig(topic)
        client = EventGridClient(config,redential=credential)
        client.emit_event"topic", "ident", {}, "event-type", "subject")
        ```

    Internally sync/async versions of the azure eventgrid clients will be called
    accordingly.
    """

    def __init__(
        self,
        config: EventGridConfig,
        credential: DefaultAzureCredential | None = None,
        async_credential: AsyncDefaultAzureCredential | None = None,
    ):
        if not credential and not async_credential:
            raise ValueError("Must provide credential or async_credential")

        if credential and async_credential:
            raise ValueError("Must provide only ONE of credential or async_credential")

        self.config = config
        self.credential: DefaultAzureCredential | None = None
        self.async_credential: AsyncDefaultAzureCredential | None = None

        if credential:
            self.credential = credential
            self._init_clients()
        else:
            self.async_credential = async_credential
            self._init_async_clients()

    def _init_clients(self):
        self.clients = {}
        for topic in self.config.topics():
            self.clients[topic] = EventGridPublisherClient(self.config.url(topic), self.credential)

    def _init_async_clients(self):
        self.async_clients = {}
        for topic in self.config.topics():
            self.async_clients[topic] = AsyncEventGridPublisherClient(
                self.config.url(topic), self.async_credential
            )

    def get_client(self, topic: str) -> EventGridPublisherClient:
        """Get the azure publisher client for the named topic."""
        return self.clients[topic]

    def get_async_client(self, topic: str) -> AsyncEventGridPublisherClient:
        """Get the async azure publisher client for the name topic."""
        return self.async_clients[topic]

    def is_sync(self):
        """Check if this client is configured to be syncrhonous."""
        return self.async_credential is None

    def emit_event(
        self, topic: str, event_type: str, subject: str, data: dict, data_version: str = "v1", **kwargs
    ) -> None:
        """Emit an event grid synchronously.

        Exceptions:

            Raises HttpResponseError exception if failed to emit
        """
        event = EventGridEvent(
            data=data, subject=subject, event_type=event_type, data_version=data_version, **kwargs
        )

        client = self.get_client(topic)
        return client.send(event)

    async def async_emit_event(
        self, topic: str, event_type: str, subject: str, data: dict, data_version: str = "v1", **kwargs
    ) -> None:
        """Emit an event grid asynchronously.

        Exceptions:

            Raises HttpResponseError exception if failed to emit
        """
        event = EventGridEvent(
            data=data, subject=subject, event_type=event_type, data_version=data_version, **kwargs
        )

        client = self.get_async_client(topic)
        return await client.send(event)
