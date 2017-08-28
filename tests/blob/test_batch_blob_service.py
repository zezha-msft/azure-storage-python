# coding: utf-8

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

import os
import unittest
import shutil
from azure.common import AzureHttpError

from azure.storage.blob.batchblobservice import BatchBlobService
from tests.testcase import (
    StorageTestCase,
)

from tests.testcase import (
    StorageTestCase,
)


class BatchBlobServiceTest(StorageTestCase):

    TEST_UPLOAD_DIR = 'test-upload-dir'
    TEST_DOWNLOAD_DIR = 'test-download-dir'

    def setUp(self):
        super(BatchBlobServiceTest, self).setUp()

        self.bs = self._create_storage_service(BatchBlobService, self.settings)

        self.container_name = self.get_resource_name('utcontainer')

        if not self.is_playback():
            self.bs.create_container(self.container_name)

    def tearDown(self):
        if not self.is_playback():
            try:
                self.bs.delete_container(self.container_name)
            except:
                pass

        return super(BatchBlobServiceTest, self).tearDown()

    def upload_test_blobs(self, num_of_blobs):
        data = b'hello world'
        for i in range(0, num_of_blobs):
            self.bs.create_blob_from_bytes(self.container_name, 'blob' + str(i), data)

    @staticmethod
    def create_test_files(directory, num_of_files):
        for i in range(0, num_of_files):
            with open(directory + '/blob' + str(i), 'wb') as stream:
                stream.write(b'hello world')

    @staticmethod
    def recreate_directory(directory_name):
        if os.path.isdir(directory_name):
            shutil.rmtree(directory_name)

        os.makedirs(directory_name)

    def test_directory_upload(self):
        # Arrange
        self.recreate_directory(self.TEST_UPLOAD_DIR)
        self.create_test_files(self.TEST_UPLOAD_DIR, 50)

        # Act
        results = self.bs.upload_directory(self.container_name, self.TEST_UPLOAD_DIR)

        # Assert
        for result in results:
            self.assertTrue(result.is_success)

    def test_directory_download(self):
        # Arrange
        self.recreate_directory(self.TEST_DOWNLOAD_DIR)
        self.upload_test_blobs(50)

        # Act
        results = self.bs.download_directory(self.container_name, os.path.abspath(self.TEST_DOWNLOAD_DIR))

        # Assert
        for result in results:
            self.assertTrue(result.is_success)


# ------------------------------------------------------------------------------
if __name__ == '__main__':
    unittest.main()
