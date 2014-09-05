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

from neutron.ddi.drivers.infoblox import config
from neutron.ddi.drivers.infoblox import connector
from neutron.ddi.drivers.infoblox import dns_controller
from neutron.ddi.drivers.infoblox.ip_allocator import get_ip_allocator
from neutron.ddi.drivers.infoblox import ipam_controller
from neutron.ddi.drivers.infoblox import object_manipulator
from neutron.ddi.drivers import neutron_ddi
import taskflow.engines
from taskflow.patterns import linear_flow


class FlowContext(object):
    def __init__(self, neutron_context, flow_name):
        self.parent_flow = linear_flow.Flow(flow_name)
        self.context = neutron_context
        self.store = {}

    def __getattr__(self, item):
        return getattr(self.context, item)


class InfobloxDDI(neutron_ddi.NeutronDDI):
    def __init__(self):
        super(InfobloxDDI, self).__init__()

        config_finder = config.ConfigFinder()
        obj_manipulator = object_manipulator.InfobloxObjectManipulator(
            connector=connector.Infoblox())
        ip_allocator = get_ip_allocator(obj_manipulator)

        self.ipam_controller = ipam_controller.InfobloxIPAMController(
            config_finder=config_finder,
            obj_manip=obj_manipulator,
            ip_allocator=ip_allocator)

        self.dns_controller = dns_controller.InfobloxDNSController(
            config_finder=config_finder,
            manipulator=obj_manipulator,
            ip_allocator=ip_allocator
        )

    def create_subnet(self, context, subnet):
        context = FlowContext(context, 'create-subnet')
        context.store['subnet'] = subnet

        retval = super(InfobloxDDI, self).create_subnet(context, subnet)

        taskflow.engines.run(context.parent_flow, store=context.store)

        return retval

    def get_additional_network_dict_params(self, network):
        return {
            'dhcp_relay_ip': network['dhcp_relay_ip'],
            'dns_relay_ip': network['dns_relay_ip']
        }
