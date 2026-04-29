import os
import tempfile
import urllib.parse
from unittest import mock

import aiofiles
import pytest
from aio_azure_clients_toolbox.clients import azure_blobs
from azure.core.exceptions import HttpResponseError
from azure.storage.blob import BlobProperties

FNAME = ".A fi~lename~ #with-12? unsafe chars \\ \t \\ ;  ü.pdf."
FNAME_DROPPED_CHARS = azure_blobs.DISALLOWED_CHARS_PAT.sub("", FNAME)


@pytest.fixture()
def absc(mock_azureblob):
    return azure_blobs.AzureBlobStorageClient("http://localhost:8000", "test-container", mock.AsyncMock())


def test_blobify_filename_no_quoting(absc):
    result1 = azure_blobs.blobify_filename(FNAME, quoting=False)
    result2 = absc.safe_blob_name(FNAME, quoting=False)
    # sanity check: we should keep this as a staticmethod ->
    result3 = azure_blobs.AzureBlobStorageClient.safe_blob_name(FNAME, quoting=False)

    assert result1 == result2 == result3
    assert "~" not in result1
    assert not result1.startswith(".")
    assert not result1.endswith(".")


def test_blobify_filename_with_quoting(absc):
    result1 = azure_blobs.blobify_filename(FNAME, quoting=True)
    result2 = absc.safe_blob_name(FNAME, quoting=True)
    # sanity check: we should keep this as a staticmethod ->
    result3 = azure_blobs.AzureBlobStorageClient.safe_blob_name(FNAME, quoting=True)

    assert result1 == result2 == result3
    assert " " not in result1
    assert "\t" not in result1
    assert "~" not in result1
    assert not result1.startswith(".")
    assert not result1.endswith(".")
    assert "%20" in result1


async def test_get_blob_sas_token(absc, mock_azureblob, mocksas):
    mockgen, fake_token = mocksas
    _, mockblobc, _ = mock_azureblob
    mockblobc.account_name = "our-company-blobs"

    result = await absc.get_blob_sas_token("bla")
    assert result == fake_token

    result2 = await absc.get_blob_sas_url("bla")
    assert result2.endswith(f"test-container/bla?{fake_token}")

    bad_name = "b l a # . pdf"
    result3 = await absc.get_blob_sas_url(bad_name)
    assert result3.endswith(f"test-container/{urllib.parse.quote(bad_name)}?{fake_token}")

    # check mocked function to see what it was called with
    assert mockgen.call_count == 3
    call = mockgen.call_args_list[0]
    permission = call[1]["permission"]
    assert permission.read and not permission.write


async def test_get_blob_sas_token_list(absc, mock_azureblob, mocksas):
    mockgen, fake_token = mocksas
    _, mockblobc, _ = mock_azureblob
    mockblobc.account_name = "our-company-blobs"

    result = await absc.get_blob_sas_token_list(["bla"])
    assert result["bla"] == fake_token

    result2 = await absc.get_blob_sas_url_list(["bla"])
    assert result2["bla"].endswith(f"test-container/bla?{fake_token}")

    # check mocked function to see what it was called with
    assert mockgen.call_count == 2
    call = mockgen.call_args_list[0]
    permission = call[1]["permission"]
    assert permission.read and not permission.write


@pytest.mark.parametrize("with_error", (True, False))
async def test_delete_blob(with_error, absc, mock_azureblob):
    _, mockblobc, _ = mock_azureblob
    if with_error:
        mockblobc.delete_blob = mock.AsyncMock(side_effect=HttpResponseError(message="this thing broke"))
    else:
        mockblobc.delete_blob.side_effect = None
        mockblobc.delete_blob = mock.AsyncMock(return_value="HEY")

    if with_error:
        with pytest.raises(azure_blobs.AzureBlobError):
            await absc.delete_blob("hey")
    else:
        assert await absc.delete_blob("hey") == "HEY"


async def test_get_blob_download_stream(absc, mock_azureblob):
    _, _, set_return = mock_azureblob
    set_return.download_blob_returns(b"HEY")
    async with absc.get_blob_download_stream("some-blob") as stream:
        assert await stream.readall() == b"HEY"


async def test_get_blob_download_stream_error(absc, mock_azureblob):
    _, mockblobc, _ = mock_azureblob
    mockblobc.download_blob = mock.AsyncMock(side_effect=HttpResponseError(message="not found"))
    with pytest.raises(azure_blobs.AzureBlobError):
        async with absc.get_blob_download_stream("some-blob"):
            pass


async def test_get_blob_download_stream_chunks(absc, mock_azureblob):
    _, _, set_return = mock_azureblob
    set_return.download_blob_returns(b"CHUNK")
    async with absc.get_blob_download_stream("some-blob") as stream:
        chunks = [chunk async for chunk in stream.chunks()]
    assert chunks == [b"CHUNK"]


async def test_get_blob_download_stream_properties(absc, mock_azureblob):
    _, mockblobc, set_return = mock_azureblob
    set_return.download_blob_returns(b"DATA")
    stream_mock = mockblobc.download_blob.return_value
    stream_mock.properties = mock.Mock()
    stream_mock.properties.etag = '"0x8DBBAF4B8A6017C"'

    async with absc.get_blob_download_stream("some-blob") as stream:
        assert stream.properties.etag == '"0x8DBBAF4B8A6017C"'


async def test_download_blob(absc, mock_azureblob):
    _, _, set_return = mock_azureblob
    set_return.download_blob_returns(b"HEY")
    assert await absc.download_blob("some-blob") == b"HEY"


async def test_download_blob_to_dir(absc, mock_azureblob):
    _, _, set_return = mock_azureblob
    set_return.download_blob_returns(b"HEY")
    with tempfile.TemporaryDirectory() as tempdir:
        new_path = await absc.download_blob_to_dir(tempdir, "blob.bla")
        assert os.path.exists(new_path)
        # check content
        async with aiofiles.open(new_path, "rb") as fl:
            assert (await fl.read()) == b"HEY"


@pytest.mark.parametrize("with_error", (True, False))
async def test_upload_blob(with_error, absc, mock_azureblob):
    _, mockblobc, _ = mock_azureblob
    if with_error:
        mockblobc.upload_blob.side_effect = HttpResponseError(message="this thing broke")
        with pytest.raises(azure_blobs.AzureBlobError):
            await absc.upload_blob("hey", "somedata")

        mockblobc.upload_blob.assert_called_once_with("somedata", blob_type="BlockBlob")
    else:
        expected = {"status": "success"}
        mockblobc.upload_blob.return_value = expected
        result1 = await absc.upload_blob("hey", "somedata")
        assert result1[0] is True
        assert result1[1]["status"] == "success"

        # try it once more with feeling
        expected["error_code"] = "SOME_ERROR"
        mockblobc.upload_blob.return_value = expected

        result2 = await absc.upload_blob("hey", "somedata")
        assert result2 == (False, expected)

        assert len(mockblobc.upload_blob.call_args_list) == 2
        for call in mockblobc.upload_blob.call_args_list:
            assert call[0][0] == "somedata"
            assert call[1]["blob_type"] == "BlockBlob"


async def test_list_blobs(absc, mock_azureblob):
    container_client, _, set_return = mock_azureblob
    set_return.list_blobs_returns([
        BlobProperties(name="some-blob", last_modified="2023-01-01T00:00:00Z"),
        BlobProperties(name="some-blob2", last_modified="2023-01-01T00:00:00Z"),
        BlobProperties(name="some-blob3", last_modified="2023-01-01T00:00:00Z"),
    ])

    blob_names = [b.name async for b in absc.list_blobs()]
    assert len(blob_names) == 3
    assert blob_names == ["some-blob", "some-blob2", "some-blob3"]


def test_chop_starting_dot_no_dot():
    assert azure_blobs.chop_starting_dot("hello") == "hello"


def test_chop_trailing_dot_no_dot():
    assert azure_blobs.chop_trailing_dot("hello") == "hello"


def test_container_name_leading_slash(mock_azureblob):
    client = azure_blobs.AzureBlobStorageClient("http://localhost:8000", "/test-container", mock.AsyncMock())
    assert client.container_name == "test-container"


async def test_upload_blob_from_url(absc, mock_azureblob):
    _, mockblobc, _ = mock_azureblob
    mockblobc.upload_blob_from_url = mock.AsyncMock(return_value={"etag": "0x123"})
    result = await absc.upload_blob_from_url("dest-blob", "https://source.example.com/blob")
    assert result == {"etag": "0x123"}
    mockblobc.upload_blob_from_url.assert_called_once_with("https://source.example.com/blob", overwrite=True)


async def test_download_blob_side_effect_list(absc, mock_azureblob):
    """Covers set_download_return with side_effect as a list"""
    _, _, set_return = mock_azureblob
    set_return.download_blob_returns(b"DEFAULT", side_effect=[b"FIRST", b"SECOND"])
    result1 = await absc.download_blob("blob1")
    assert result1 == b"FIRST"
    result2 = await absc.download_blob("blob2")
    assert result2 == b"SECOND"


async def test_download_blob_side_effect_exception(absc, mock_azureblob):
    """Covers set_download_return with non-list side_effect (exception on async iter)"""
    _, _, set_return = mock_azureblob
    set_return.download_blob_returns(b"DEFAULT", side_effect=RuntimeError("boom"))
    # The side_effect is set on the async iter, which would raise on iteration
    # but readall still works because it's a separate mock
    result = await absc.download_blob("blob")
    assert result == b"DEFAULT"


async def test_async_iter_aiter_exception():
    """Covers AsyncIterImplementation.__aiter__ with exception side_effect"""
    from aio_azure_clients_toolbox.testing_utils.fixtures import AsyncIterImplementation
    ai = AsyncIterImplementation()
    ai.side_effect = ValueError("test error")
    with pytest.raises(ValueError, match="test error"):
        async for _ in ai:
            pass


async def test_async_iter_call_method():
    """Covers AsyncIterImplementation._call__ method"""
    from aio_azure_clients_toolbox.testing_utils.fixtures import AsyncIterImplementation
    ai = AsyncIterImplementation()
    ai.return_value = "hello"
    result = await ai._call__()
    assert result == "hello"

    # With exception side_effect
    ai2 = AsyncIterImplementation()
    ai2.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        await ai2._call__()

    # With iterable side_effect
    ai3 = AsyncIterImplementation()
    ai3.side_effect = [1, 2, 3]
    ai3.return_value = "fallback"
    result = await ai3._call__()
    assert result == "fallback"


async def test_get_blob_client_empty_url(mock_azureblob):
    client = azure_blobs.AzureBlobStorageClient("http://x/", "container", mock.AsyncMock())
    # Force az_storage_url to empty to trigger the guard
    client.az_storage_url = ""
    with pytest.raises(AttributeError, match="improperly configured"):
        async with client.get_blob_client("blob"):
            pass
