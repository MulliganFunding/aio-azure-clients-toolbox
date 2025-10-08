from typing import Protocol, runtime_checkable

from azure.identity.aio import DefaultAzureCredential


@runtime_checkable
class CredentialFactory(Protocol):
    def __call__(self) -> DefaultAzureCredential:
        ...
