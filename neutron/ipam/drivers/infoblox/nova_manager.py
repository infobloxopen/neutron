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

import novaclient.v1_1.client as nclient
from novaclient import exceptions as novaexc
from oslo.config import cfg

import logging

LOG = logging.getLogger(__name__)


class NovaManager(object):
    _nova_client = None

    def __init__(self):
        if not NovaManager._nova_client:
            NovaManager._nova_client = nclient.Client(
                cfg.CONF.nova_admin_username,
                cfg.CONF.nova_admin_password,
                None,  # project_id - not actually used
                auth_url=cfg.CONF.nova_admin_auth_url,
                tenant_id=cfg.CONF.nova_admin_tenant_id,
                service_type='compute')
        self.nova = NovaManager._nova_client

    def get_instance_name_by_id(self, instance_id):
        try:
            instance = self.nova.servers.get(instance_id)
            if instance.human_id:
                return instance.human_id
        except (novaexc.NotFound, novaexc.BadRequest):
            LOG.debug(_("Instance not found: %{instance_id}s"),
                      {'instance_id': instance_id})
        return instance_id
