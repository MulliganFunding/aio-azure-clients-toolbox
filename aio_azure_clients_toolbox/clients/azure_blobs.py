import datetime
import os
import re
import typing
import urllib.parse
from contextlib import asynccontextmanager

import aiofiles
from azure.core.exceptions import HttpResponseError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from azure.storage.blob.aio import BlobClient, BlobServiceClient

# These limits are inclusive; names must not exceed these counts
BLOB_NAME_CHAR_LIMIT = 1024
# Even though we'll url safe encode below, we've seen special
# headaches with these chars, so we specifically strip them
DISALLOWED_CHARS_PAT = re.compile(r"[~#\\]")


def chop_starting_dot(name: str) -> str:
    if name.startswith("."):
        return name[1:]
    return name


def chop_trailing_dot(name: str) -> str:
    if name.endswith("."):
        return name[:-1]
    return name


def blobify_filename(name: str, quoting=False) -> str:
    """
    see: https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blobs-introduction#blobs

    A blob name can contain any combination of characters.

    A blob name must be at least one character long and cannot
    be more than 1,024 characters long, for blobs in Azure Storage.

    Blob names are case-sensitive.

    Reserved URL characters must be properly escaped.*

    If your account does not have a hierarchical namespace,
    then the number of path segments comprising the blob name cannot exceed 254.
    A path segment is the string between consecutive delimiter characters (e.g., the forward slash '/')
    that corresponds to the name of a virtual directory.

    Avoid blob names that end with a dot, a forward slash, a backslash, or a sequence
    or combination of the these. No path segments should end with a dot.

    * urlsafe encode any blob URLs! Not the names!
    """
    name = name.strip()
    name = DISALLOWED_CHARS_PAT.sub("", name)
    name = chop_trailing_dot(chop_starting_dot(name))
    if quoting:
        return (urllib.parse.quote(name))[:BLOB_NAME_CHAR_LIMIT]
    return name[:BLOB_NAME_CHAR_LIMIT]


class AzureBlobError(Exception):
    def __init__(self, azure_http_resp_error: HttpResponseError):
        self.reason = azure_http_resp_error.reason
        self.status_code = azure_http_resp_error.status_code
        self.message = azure_http_resp_error.message
        super().__init__(self.message)


class AzureBlobStorageClient:
    """
    Args:
        az_storage_url (str): The URI to the storage account.
        container_name (str): The container name for the blob.
        credentials (DefaultAzureCredential): The credentials with which to authenticate.
    """

    __slots__ = ["az_storage_url", "container_name", "credentials"]

    def __init__(
        self,
        az_storage_url: str,
        container_name: str,
        credentials: DefaultAzureCredential,
    ):
        if not az_storage_url.endswith("/"):
            az_storage_url = f"{az_storage_url}/"

        self.az_storage_url: str = az_storage_url

        if container_name.startswith("/"):
            container_name = container_name[1:]

        self.container_name = container_name
        self.credentials = credentials

    @staticmethod
    def safe_blob_name(blob_name: str, quoting=False) -> str:
        """
        Run a filter on blob names to make them 'safer'.

        The most reliable blob names are urlencoded, but it's not strictly required
        outside of in sas-token-urls.

        Args:
            blob_name (str): The name of the blob.
            quoting (bool): Whether to urlsafe encode the name.
        Returns:
            str: The 'safer' blob name.
        """
        return blobify_filename(blob_name, quoting=quoting)

    async def delete_blob(self, blob_name: str) -> None:
        """delete a blob from the container.

        Args:
            blob_name (str): The name of the blob.
        Raises:
            AzureBlobError: If the blob cannot be deleted.
        Returns: None
        """
        async with self.get_blob_client(blob_name) as client:
            return await client.delete_blob()

    async def download_blob(self, blob_name: str) -> bytes:
        """Download a blob from the container into bytes in memory.

        Args:
            blob_name (str): The name of the blob.
        Raises:
            AzureBlobError: If the blob cannot be downloaded.
        Returns:
            bytes: *ALL* bytes of the blob.
        """
        async with self.get_blob_client(blob_name) as client:
            stream = await client.download_blob()
            return await stream.readall()

    async def download_blob_to_dir(self, workspace_dir: str, blob_name: str) -> str:
        """
        Download Blob to a workspace_dir.

        Args:
            workspace_dir (str): The directory to save the blob.
            blob_name (str): The name of the blob.
        Raises:
            AzureBlobError: If the blob cannot be downloaded.
        Returns:
            str: The path to the saved blob.
        """
        save_path = os.path.join(workspace_dir, os.path.basename(blob_name))

        # Write file into file path in tempdir
        async with aiofiles.open(save_path, "wb") as fl:
            async with self.get_blob_client(blob_name) as client:
                stream = await client.download_blob()
                # Read data in chunks to avoid loading all into memory at once
                async for chunk in stream.chunks():
                    # `chunk` is a byte array
                    await fl.write(chunk)
        return save_path

    async def upload_blob(
        self,
        blob_name: str,
        file_data: bytes
        | str
        | typing.Iterable[typing.AnyStr]
        | typing.AsyncIterable[typing.AnyStr]
        | typing.IO[typing.AnyStr],
        **kwargs,
    ) -> tuple[bool, dict]:
        """Upload a blob to the container.

        Args:
            blob_name (str): The name of the blob.
            file_data (Union[bytes, str, Iterable, AsyncIterable, IO]): The data to upload.
            **kwargs: Additional keyword arguments (passed to `BlobClient.upload_blob method`).

        Raises:
            AzureBlobError: If the blob cannot be uploaded.
        Returns:
            tuple[bool, dict]: A tuple of a boolean indicating success and the result.
        """
        async with self.get_blob_client(blob_name) as client:
            result = await client.upload_blob(
                file_data,
                blob_type="BlockBlob",
                **kwargs,  # type: ignore
            )

        if result.get("error_code") is not None:
            return False, result

        return True, result

    async def upload_blob_from_url(
        self,
        blob_name: str,
        file_url: str,
        overwrite=True,
    ):
        """
        Upload a blob from another URL (can be blob-url with a sas-token)

        # Note: upload_blob_from_url means it will *overwrite* destination if it exists!

        `result` usually looks like this:
            {
                "etag": "\"0x8DBBAF4B8A6017C\"",
                "last_modified": "2023-09-21T22:47:23+00:00",
                "content_md5": null,
                "client_request_id": "d3e9c022-58d0-11ee-9777-422808c7c565",
                "request_id": "b855e9cc-701e-0035-7ddd-ec4cc0000000",
                "version": "2023-08-03",
                "version_id": "2023-09-21T22:47:23.5730812Z",
                "date": "2023-09-21T22:47:23+00:00",
                "request_server_encrypted": true,
                "encryption_key_sha256": null,
                "encryption_scope": null
            }

        Args:
            blob_name (str): The name of the blob.
            file_url (str): The URL of the file to upload.
            overwrite (bool): Whether to overwrite the destination if it exists.
        Raises:
            AzureBlobError: If the blob cannot be uploaded.
        Returns:
            dict: The result of the upload request.
        """
        async with self.get_blob_client(blob_name) as client:
            return await client.upload_blob_from_url(file_url, overwrite=overwrite)

    async def get_blob_sas_token(self, blob_name: str, expiry: datetime.datetime | None = None) -> str:
        """
        Returns a read-only sas token for the blob with an automatically generated
        user delegation key. For more than one, it's more efficient to call
        `get_blob_sas_token_list` (below).

        Args:
            blob_name (str): The name of the blob.
            expiry (Optional[datetime.datetime]): The expiry time of the token.
        Returns:
            str: The sas token.
        """
        now = datetime.datetime.now(tz=datetime.UTC)
        if expiry is None:
            expiry = now + datetime.timedelta(hours=1)

        async with self.get_blob_service_client() as blob_service_client:
            user_delegation_key = await blob_service_client.get_user_delegation_key(now, expiry)
            return generate_blob_sas(
                blob_service_client.account_name,
                self.container_name,
                blob_name,
                user_delegation_key=user_delegation_key,
                permission=BlobSasPermissions(read=True),
                expiry=expiry,
            )

    async def get_blob_sas_token_list(
        self,
        blob_names: list[str],
        expiry: datetime.datetime | None = None,
    ) -> dict[str, str]:
        """
        Returns a dict of blob-name -> read-only sas tokens using an automatically
        generated user delegation key.

        This function has the benefit of reusing a single BlobServiceClient
        for all tokens generated, so it will be a lot quicker than creating a
        new BlobServiceClient for *each* name.

        Args:
            blob_names (List[str]): A list of blob names.
            expiry (Optional[datetime.datetime]): The expiry time of the token.
        Returns:
            dict: A dict of blob-name -> sas token.
        """
        now = datetime.datetime.now(tz=datetime.UTC)
        if expiry is None:
            expiry = now + datetime.timedelta(hours=1)

        async with self.get_blob_service_client() as blob_service_client:
            user_delegation_key = await blob_service_client.get_user_delegation_key(now, expiry)

            tokens = {}
            for blob_name in blob_names:
                token = generate_blob_sas(
                    blob_service_client.account_name,
                    self.container_name,
                    blob_name,
                    user_delegation_key=user_delegation_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=expiry,
                )
                tokens[blob_name] = token
            return tokens

    def _make_blob_url(self, blob_name: str, sas_token: str) -> str:
        """
        We have to urlsafe encode the blob-name to be able to retrieve it.

        The implementation of `BlobClient.url` *also* safe-encodes the container-name!

        Args:
            blob_name (str): The name of the blob.
            sas_token (str): The sas token.
        Returns:
            str: The (urlsafe encoded) URL to the blob with the sas token parameter included.
        """
        safecontainer = urllib.parse.quote(self.container_name)
        safename = urllib.parse.quote(blob_name)
        return f"{self.az_storage_url}{safecontainer}/{safename}?{sas_token}"

    async def get_blob_sas_url(self, blob_name: str, expiry: datetime.datetime | None = None) -> str:
        """Returns a full download URL with sas token

        Args:
            blob_name (str): The name of the blob.
            expiry (Optional[datetime.datetime]): The expiry time of the token.
        Returns:
            str: The full download URL with sas token.
        """
        sas_token = await self.get_blob_sas_token(blob_name, expiry=expiry)
        return self._make_blob_url(blob_name, sas_token)

    async def get_blob_sas_url_list(
        self,
        blob_names: list[str],
        expiry: datetime.datetime | None = None,
    ) -> dict[str, str]:
        """
        Returns a dict of blob-name -> download URL with sas token

        Args:
            blob_names (List[str]): A list of blob names.
            expiry (Optional[datetime.datetime]): The expiry time of the token.
        Returns:
            dict: A dict of blob-name -> download-URL-with-sas-token.
        """
        tokens = await self.get_blob_sas_token_list(blob_names, expiry=expiry)
        results = {blob_name: self._make_blob_url(blob_name, token) for blob_name, token in tokens.items()}
        return results

    def get_blob_service_client(self) -> BlobServiceClient:
        """
        Simple method to construct BlobServiceClient.

        Note: calling `async with blob_service_client()...` *opens*
        a pipeline which will exit afterward. Thus, you need to either
        open-close a single one of these manually or throw it away
        after every async context manager session.

        Args:
            None
        Returns:
            BlobServiceClient: The blob service client.
        """
        return BlobServiceClient(
            self.az_storage_url,
            credential=self.credentials,  # type: ignore
        )

    @asynccontextmanager
    async def get_blob_client(self, blob_name: str) -> typing.AsyncIterator[BlobClient]:
        """Simple async context manager to get a BlobClient.

        Args:
            blob_name (str): The name of the blob.
        Raises:
            AttributeError: If `az_storage_url` is not configured.
            AzureBlobError: If the blob cannot be accessed.
        Returns:
            BlobClient: The blob client.
        """
        if not self.az_storage_url:
            raise AttributeError("`az_storage_url` is improperly configured")

        async with self.get_blob_service_client() as blob_service_client:
            client = blob_service_client.get_blob_client(self.container_name, blob_name)
            try:
                yield client  # type: ignore
            except HttpResponseError as exc:
                raise AzureBlobError(exc) from exc
