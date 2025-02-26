# Copyright 2019 The Keras Tuner Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"Cloud service related functionality."

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import concurrent.futures
import copy
import time
import requests
import json
from datetime import datetime
from kerastuner.abstractions.display import warning, info, section
from kerastuner.abstractions.display import display_settings

DISABLE = 'disable'
AUTH_ERROR = 'authentication error'
CONNECT_ERROR = 'connection error'
UPLOAD_ERROR = 'upload error'
OK = 'ok'
ERROR = 'error'


def _normalize_data_to_send(info):
    """Cleans up the data to send to the cloud service.

    Args:
        info (dict): the data to send

    Returns:
      dict: the info object, cleaned.
    """
    # Remove the parts of the data that are unbounded in size.
    info = copy.deepcopy(info)
    for key in ['model_config', 'epoch_history']:
        if key in info:
            del info[key]
    return info


def send_to_backend(url, api_key, info_type, info):
    """Sends data to the cloud service.

    Args:
        info_type (str): type of information sent
        info (dict): the data to send
    """
    response = requests.post(
        url,
        headers={'X-AUTH': api_key},
        json={
            'type': info_type,
            'data': _normalize_data_to_send(info)
        })

    if not response.ok:
        try:
            response_json = response.json()
        except json.decoder.JSONDecodeError:
            warning('Cloud service down -- data not uploaded: %s' %
                    response.text)
            return CONNECT_ERROR

        if response_json['status'] == 'Unauthorized':
            warning('Invalid backend API key.')
            return AUTH_ERROR
        else:
            warning('Warning! Cloud service upload failed: %s' % response.text)
            return UPLOAD_ERROR
        return ERROR
    else:
        return OK


class CloudService():
    """ Cloud service reporting mechanism"""

    def __init__(self):
        self.enabled = False
        self.status = "disable"
        self.base_url = (
            'https://us-central1-kerastuner-prod.cloudfunctions.net/api/')
        self.api_key = None
        self.log_interval = 5
        self.last_update = -1
        self.executor = concurrent.futures.ProcessPoolExecutor()

    def enable(self, api_key, url=None):
        """enable cloud service by setting API key"""
        self.api_key = api_key
        if url:
            self.base_url = url
        if self._check_access():
            info("Cloud service enabled - Go to https://.. to track your "
                 "tuning results in realtime.")
            self.status = OK
            self.enabled = True
        else:
            warning("Invalid cloud API key")
            self.status = AUTH_ERROR
            self.enabled = False

    def complete(self):
        """Makes sure that all cloud requests have been sent."""
        self.executor.shutdown(wait=True)
        # In case the user wants to do multiple hypertuning sessions,
        # we open another process pool.
        self.executor = concurrent.futures.ProcessPoolExecutor()

    def _check_access(self):
        "Check is the user API key is valid"

        # special case for unit-test
        if self.api_key == 'test_key_true':
            return True

        if self.api_key == 'test_key_false':
            return False

        url = self._url_join(self.base_url, 'v1/check-access')
        response = requests.post(
            url,
            headers={'X-AUTH': self.api_key})
        return response.ok

    def _url_join(self, *parts):
        """Joins a base url with one or more path segments.

        This joins https://example.com/a/b/ with 'update', resulting
        in https://example.com/a/b/update. Removing the trailing slash from
        the first argument will yield the same output.

        Args:
            parts (list): the URL parts to join.

        Returns:
            str: A url.
        """
        return "/".join(map(lambda fragment: fragment.rstrip('/'), parts))

    def _send_nonblocking(self, info_type, info):

        if not self.enabled:
            return

        url = self._url_join(self.base_url, 'v1/update')
        self.executor.submit(send_to_backend, url,
                             self.api_key, info_type, info)

    def _send_blocking(self, info_type, info):
        """Send data to the cloud service

        Args:
            info_type (str): type of information sent
            info (dict): the data to send
        """

        # skip if API key don't work or service down
        if not self.enabled:
            return 'disabled'

        url = self._url_join(self.base_url, 'v1/update')
        self.status = send_to_backend(url, self.api_key, info_type, info)

    def send_status(self, status):
        "send tuner status for realtime tracking"
        ts = time.time()
        if ts - self.last_update > self.log_interval:
            self._send_nonblocking("status", status)
            self.last_update = ts

    def send_results(self, results):
        self._send_nonblocking("results", results)

    def summary(self, extended=False):
        "display cloud service status summary"
        human_time = datetime.utcfromtimestamp(self.last_update)
        human_time = human_time.strftime('%Y-%m-%dT%H:%M:%SZ')

        section('Cloud service status')
        info = {
            "status": self.status,
            "last update": human_time
            }
        display_settings(info)

    def get_config(self):
        # !DO NOT record API key
        res = {
            "enabled": self.enabled,
            "status": self.status,
            "last_update": self.last_update
        }
        return res
