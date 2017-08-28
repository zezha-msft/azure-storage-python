# -------------------------------------------------------------------------
# Copyright (c) Microsoft.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# --------------------------------------------------------------------------

from os import listdir
from os.path import isfile, join, abspath
import concurrent.futures
import multiprocessing
from azure.storage.blob.blockblobservice import BlockBlobService
from azure.storage.blob.models import (
    BatchTaskResult,
    _BatchBlobTask,
)
from azure.storage.common._constants import (
    SERVICE_HOST_BASE,
    DEFAULT_PROTOCOL,
)


class BatchBlobService(BlockBlobService):
    '''
        BatchBlobService allows you to upload all files under a local directory as block blobs
        to a storage container, and also download all the blobs of a container into a directory.
        BatchBlobService only uploads files directly under a directory, not files under sub-directories.

        :ivar int DEFAULT_CONCURRENT_NUM_OF_FILES:
            This default specifies how many files should be uploaded in parallel. The default number is
            obtained by dividing the number of cpu count (including hyper-threading) by 2, which is
            the default max connection per file.
    '''

    DEFAULT_CONCURRENT_NUM_OF_FILES = multiprocessing.cpu_count() / 2

    def __init__(self, account_name=None, account_key=None, sas_token=None,
                 is_emulated=False, protocol=DEFAULT_PROTOCOL, endpoint_suffix=SERVICE_HOST_BASE,
                 custom_domain=None, request_session=None, connection_string=None, socket_timeout=None):
        '''
            :param str account_name:
                The storage account name. This is used to authenticate requests
                signed with an account key and to construct the storage endpoint. It
                is required unless a connection string is given, or if a custom
                domain is used with anonymous authentication.
            :param str account_key:
                The storage account key. This is used for shared key authentication.
                If neither account key or sas token is specified, anonymous access
                will be used.
            :param str sas_token:
                 A shared access signature token to use to authenticate requests
                 instead of the account key. If account key and sas token are both
                 specified, account key will be used to sign. If neither are
                 specified, anonymous access will be used.
            :param bool is_emulated:
                Whether to use the emulator. Defaults to False. If specified, will
                override all other parameters besides connection string and request
                session.
            :param str protocol:
                The protocol to use for requests. Defaults to https.
            :param str endpoint_suffix:
                The host base component of the url, minus the account name. Defaults
                to Azure (core.windows.net). Override this to use the China cloud
                (core.chinacloudapi.cn).
            :param str custom_domain:
                The custom domain to use. This can be set in the Azure Portal. For
                example, 'www.mydomain.com'.
            :param requests.Session request_session:
                The session object to use for http requests.
            :param str connection_string:
                If specified, this will override all other parameters besides
                request session. See
                http://azure.microsoft.com/en-us/documentation/articles/storage-configure-connection-string/
                for the connection string format
            :param int socket_timeout:
                If specified, this will override the default socket timeout. The timeout specified is in seconds.
                See DEFAULT_SOCKET_TIMEOUT in _constants.py for the default value.
        '''

        super(BatchBlobService, self).__init__(account_name, account_key, sas_token, is_emulated,
                                               protocol, endpoint_suffix, custom_domain, request_session,
                                               connection_string, socket_timeout)

    def _upload_file(self, task):

        try:
            self.create_blob_from_path(task.container_name, task.blob_name, task.file_path)
        except Exception as e:
            return BatchTaskResult(task.container_name, task.blob_name, task.file_path, is_success=False, exception=e)

        return BatchTaskResult(task.container_name, task.blob_name, task.file_path, is_success=True)

    def upload_directory(self, container_name, directory_path,
                         concurrent_number_of_upload=DEFAULT_CONCURRENT_NUM_OF_FILES):
        self.create_container(container_name)

        upload_tasks = [_BatchBlobTask(container_name, file_name, join(directory_path, file_name))
                        for file_name in listdir(directory_path) if isfile(join(directory_path, file_name))]
        executor = concurrent.futures.ThreadPoolExecutor(concurrent_number_of_upload)
        result = list(executor.map(self._upload_file, upload_tasks))
        return result

    def _download_blob(self, task):
        try:
            self.get_blob_to_path(task.container_name, task.blob_name, task.file_path)
        except Exception as e:
            return BatchTaskResult(task.container_name, task.blob_name, task.file_path, is_success=False, exception=e)

        return BatchTaskResult(task.container_name, task.blob_name, task.file_path, is_success=True)

    def download_directory(self, container_name, directory_path,
                           concurrent_number_of_download=DEFAULT_CONCURRENT_NUM_OF_FILES):
        download_tasks = [_BatchBlobTask(container_name, blob.name, join(directory_path, blob.name))
                          for blob in self.list_blobs(container_name)]
        executor = concurrent.futures.ThreadPoolExecutor(concurrent_number_of_download)
        result = list(executor.map(self._download_blob, download_tasks))
        return result
