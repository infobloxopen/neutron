# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2014 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import functools
import re

from oslo.config import cfg
import requests
from requests import exceptions as req_exc
import urllib
import urlparse

from neutron.ipam.drivers.infoblox import exceptions as exc
from oslo_serialization import jsonutils
from oslo_log import log as logging


OPTS = [
    cfg.StrOpt('infoblox_wapi', help=_("REST API url")),
    cfg.StrOpt('infoblox_username', help=_("User name")),
    cfg.StrOpt('infoblox_password', help=_("User password")),
    cfg.BoolOpt('infoblox_sslverify', default=False),
    cfg.IntOpt('infoblox_http_pool_connections', default=100),
    cfg.IntOpt('infoblox_http_pool_maxsize', default=100),
    cfg.IntOpt('infoblox_http_request_timeout', default=120)
]

cfg.CONF.register_opts(OPTS)


LOG = logging.getLogger(__name__)


def reraise_neutron_exception(func):
    @functools.wraps(func)
    def callee(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except req_exc.Timeout as e:
            LOG.error(e.message)
            raise exc.InfobloxTimeoutError(e)
        except req_exc.RequestException as e:
            LOG.error(_("HTTP request failed: %s"), e)
            raise exc.InfobloxConnectionError(reason=e)
    return callee


class Infoblox(object):
    """
    Infoblox class

    Defines methods for getting, creating, updating and
    removing objects from an Infoblox server instance.
    """

    CLOUD_WAPI_MAJOR_VERSION = 2

    def __init__(self):
        """
        Initialize a new Infoblox object instance
        Args:
            config (str): Path to the Infoblox configuration file
        """
        self.wapi = cfg.CONF.infoblox_wapi
        self.username = cfg.CONF.infoblox_username
        self.password = cfg.CONF.infoblox_password
        self.sslverify = cfg.CONF.infoblox_sslverify
        self.request_timeout = cfg.CONF.infoblox_http_request_timeout

        if not self.wapi or not self.username or not self.password:
            raise exc.InfobloxIsMisconfigured()

        self.is_cloud = self.is_cloud_wapi(self.wapi)
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=cfg.CONF.infoblox_http_pool_connections,
            pool_maxsize=cfg.CONF.infoblox_http_pool_maxsize)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.auth = (self.username, self.password)
        self.session.verify = self.sslverify

    @staticmethod
    def is_cloud_wapi(wapi_url):
        version_match = re.search('\/wapi\/v(\d+)\.(\d+)', wapi_url)
        if version_match:
            if int(version_match.group(1)) >= Infoblox.CLOUD_WAPI_MAJOR_VERSION:
                return True
        return False

    def _construct_url(self, relative_path, query_params=None, extattrs=None):
        if query_params is None:
            query_params = {}
        if extattrs is None:
            extattrs = {}

        if not relative_path or relative_path[0] == '/':
            raise ValueError('Path in request must be relative.')
        query = ''
        if query_params or extattrs:
            query = '?'

        if extattrs:
            attrs_queries = []
            for key, value in extattrs.items():
                attrs_queries.append('*' + key + '=' + value['value'])
            query += '&'.join(attrs_queries)
        if query_params:
            if len(query) > 1:
                query += '&'
            query += urllib.urlencode(query_params)

        baseurl = urlparse.urljoin(self.wapi, urllib.quote(relative_path))
        return baseurl + query

    @staticmethod
    def _validate_objtype_or_die(objtype, objtype_expected=True):
        if not objtype:
            raise ValueError('WAPI object type can\'t be empty.')
        if objtype_expected and '/' in objtype:
            raise ValueError('WAPI object type can\'t contain slash.')

    @reraise_neutron_exception
    def get_object(self, objtype, payload=None, return_fields=None,
                   extattrs=None, proxy=False):
        """
        Retrieve a list of Infoblox objects of type 'objtype'
        Args:
            objtype  (str): Infoblox object type, e.g. 'network', 
                            'range', etc.
            payload (dict): Payload with data to send
            return_fields (list): List of fields to be returned
            extattrs      (list): List of Extensible Attributes
        Returns:
            A list of the Infoblox objects requested
        Raises:
            InfobloxObjectNotFound
        """
        if return_fields is None:
            return_fields = []
        if extattrs is None:
            extattrs = {}

        self._validate_objtype_or_die(objtype, objtype_expected=False)

        query_params = dict()
        if payload:
            query_params = payload

        if return_fields:
            query_params['_return_fields'] = ','.join(return_fields)

        # Some get requests like 'ipv4address' should be always
        # proxied to GM on Hellfire
        # If request is cloud and proxy is not forced yet,
        # then plan to do 2 request:
        # - the first one is not proxified to GM
        # - the second is proxified to GM
        urls = dict()
        urls['direct'] = self._construct_url(objtype, query_params, extattrs)
        if self.is_cloud:
            query_params['_proxy_search'] = 'GM'
            urls['proxy'] = self._construct_url(objtype, query_params, extattrs)

        url = urls['direct']
        if self.is_cloud and proxy:
            url = urls['proxy']

        headers = {'Content-type': 'application/json'}

        ib_object = self._get_object(objtype, url, headers)
        if ib_object:
            return ib_object

        # if cloud api and proxy is not used, use proxy
        if self.is_cloud and not proxy:
            return self._get_object(objtype, urls['proxy'], headers)

        return None

    def _get_object(self, objtype, url, headers):
        r = self.session.get(url,
                             verify=self.sslverify,
                             timeout=self.request_timeout,
                             headers=headers)

        if r.status_code == requests.codes.UNAUTHORIZED:
            raise exc.InfobloxBadWAPICredential(response='')

        if r.status_code != requests.codes.ok:
            raise exc.InfobloxSearchError(
                response=jsonutils.loads(r.content),
                objtype=objtype,
                content=r.content,
                code=r.status_code)

        return jsonutils.loads(r.content)

    @reraise_neutron_exception
    def create_object(self, objtype, payload,
                     return_fields=None,  delegate_member=None):
        """
        Create an Infoblox object of type 'objtype'
        Args:
            objtype        (str): Infoblox object type,
                                  e.g. 'network', 'range', etc.
            payload       (dict): Payload with data to send
            return_fields (list): List of fields to be returned
        Returns:
            The object reference of the newly create object
        Raises:
            InfobloxException
        """
        if self.is_cloud and delegate_member and delegate_member.delegate:
            payload.update({"cloud_info": {
                    "delegated_member": delegate_member.specifier}})

        if not return_fields:
            return_fields = []

        self._validate_objtype_or_die(objtype)

        query_params = dict()

        if return_fields:
            query_params['_return_fields'] = ','.join(return_fields)

        url = self._construct_url(objtype, query_params)
        data = jsonutils.dumps(payload)
        headers = {'Content-type': 'application/json'}
        r = self.session.post(url,
                              data=data,
                              verify=self.sslverify,
                              timeout=self.request_timeout,
                              headers=headers)

        if r.status_code == requests.codes.UNAUTHORIZED:
            raise exc.InfobloxBadWAPICredential(response='')

        if r.status_code != requests.codes.CREATED:
            raise exc.InfobloxCannotCreateObject(
                response=jsonutils.loads(r.content),
                objtype=objtype,
                content=r.content,
                args=payload,
                code=r.status_code)

        return jsonutils.loads(r.content)

    @reraise_neutron_exception
    def call_func(self, func_name, ref, payload, return_fields=None):
        if not return_fields:
            return_fields = []

        query_params = dict()
        query_params['_function'] = func_name

        if return_fields:
            query_params['_return_fields'] = ','.join(return_fields)

        url = self._construct_url(ref, query_params)

        headers = {'Content-type': 'application/json'}
        r = self.session.post(url,
                              data=jsonutils.dumps(payload),
                              verify=self.sslverify,
                              headers=headers)

        if r.status_code == requests.codes.UNAUTHORIZED:
            raise exc.InfobloxBadWAPICredential(response='')

        if r.status_code not in (requests.codes.CREATED,
                                 requests.codes.ok):
            raise exc.InfobloxFuncException(
                response=jsonutils.loads(r.content),
                ref=ref,
                func_name=func_name,
                content=r.content,
                code=r.status_code)

        return jsonutils.loads(r.content)

    @reraise_neutron_exception
    def update_object(self, ref, payload, return_fields=None):
        """
        Update an Infoblox object
        Args:
            ref      (str): Infoblox object reference
            payload (dict): Payload with data to send
        Returns:
            The object reference of the updated object
        Raises:
            InfobloxException
        """
        query_params = {}
        if return_fields:
            query_params['_return_fields'] = ','.join(return_fields)

        headers = {'Content-type': 'application/json'}
        r = self.session.put(self._construct_url(ref, query_params),
                             data=jsonutils.dumps(payload),
                             verify=self.sslverify,
                             timeout=self.request_timeout,
                             headers=headers)

        if r.status_code == requests.codes.UNAUTHORIZED:
            raise exc.InfobloxBadWAPICredential(response='')

        if r.status_code != requests.codes.ok:
            raise exc.InfobloxCannotUpdateObject(
                response=jsonutils.loads(r.content),
                ref=ref,
                content=r.content,
                code=r.status_code)

        return jsonutils.loads(r.content)

    @reraise_neutron_exception
    def delete_object(self, ref):
        """
        Remove an Infoblox object
        Args:
            ref      (str): Object reference
        Returns:
            The object reference of the removed object
        Raises:
            InfobloxException
        """
        r = self.session.delete(self._construct_url(ref),
                                verify=self.sslverify,
                                timeout=self.request_timeout)

        if r.status_code == requests.codes.UNAUTHORIZED:
            raise exc.InfobloxBadWAPICredential(response='')

        if r.status_code != requests.codes.ok:
            raise exc.InfobloxCannotDeleteObject(
                response=jsonutils.loads(r.content),
                ref=ref,
                content=r.content,
                code=r.status_code)

        return jsonutils.loads(r.content)
