from typing import Protocol

from azure.identity.aio import DefaultAzureCredential


class CredentialFactory(Protocol):
    def __call__(self) -> DefaultAzureCredential:
        ...
