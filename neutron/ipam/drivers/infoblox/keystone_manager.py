# Copyright 2014 Infoblox.
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

from keystoneclient.v2_0 import client as kclient
from oslo.config import cfg

import logging

LOG = logging.getLogger(__name__)


class KeystoneClient(object):
    def __init__(self):
        username=cfg.CONF.nova_admin_username
        password=cfg.CONF.nova_admin_password
        auth_url=(cfg.CONF.keystone_authtoken.auth_url+'/v2.0')
        tenant_id=cfg.CONF.nova_admin_tenant_id
        self.keystone = kclient.Client(username=username,
                                       password=password,
                                       tenant_id=tenant_id,
                                       auth_url=auth_url)

    def get_tenant_name_by_id(self, tenant_id):
        tenant_name = None
        tenant = self.keystone.tenants.get(tenant_id)
        if tenant:
            tenant_name = tenant.name
        return tenant_name


__kclient = None
__tenant_id_map = {}

def get_tenant_name_by_id(tenant_id):
    global __kclient
    global __tenant_id_map

    if not __kclient:
        __kclient = KeystoneClient()

    if tenant_id not in __tenant_id_map:
        tenant_name = __kclient.get_tenant_name_by_id(tenant_id)
        if tenant_name:
            __tenant_id_map[tenant_id] = tenant_name
        else:
            tenant_name = 'None'
    else:
        tenant_name = __tenant_id_map[tenant_id]

    return tenant_name

