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

import abc

import six

from neutron.ipam.drivers import neutron_db
from oslo_log import log as logging

# Ports with the following 'device_owner' values will not prevent
# network deletion.  If delete_network() finds that all ports on a
# network have these owners, it will explicitly delete each port
# and allow network deletion to continue.  Similarly, if delete_subnet()
# finds out that all existing IP Allocations are associated with ports
# with these owners, it will allow subnet deletion to proceed with the
# IP allocations being cleaned up by cascade.
AUTO_DELETE_PORT_OWNERS = ['network:dhcp']

LOG = logging.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class DHCPController(neutron_db.NeutronPluginController):
    """Base class for IPAM DHCP controller. Incapsulates logic for handling
    DHCP service related actions.
    """

    @abc.abstractmethod
    def configure_dhcp(self, context, backend_subnet, dhcp_params):
        """Implement this if you need extra actions to be taken on DHCP server
        during subnet creation.
        :param backend_subnet: models_v2.Subnet object, represents a subnet
         being created
        :param dhcp_params: dict with DHCP arguments, such as dns_nameservers,
         and host_routes
         """
        pass

    @abc.abstractmethod
    def reconfigure_dhcp(self, context, backend_subnet, dhcp_params):
        """This is called on subnet update. Implement if DHCP needs to be
        reconfigured on subnet change
        :param backend_subnet: models_v2.Subnet object being updated
        :param dhcp_params: dict with DHCP parameters, such as DNS nameservers,
         and host routes
         """
        pass

    @abc.abstractmethod
    def disable_dhcp(self, context, backend_subnet):
        """This is called on subnet delete. Implement if DHCP service needs to
        be disabled for a given subnet.
        :param backend_subnet: models_v2.Subnet object being deleted
        """
        pass

    @abc.abstractmethod
    def dhcp_is_enabled(self, context, backend_subnet):
        """Returns True if DHDC service is enabled for a subnet, False
        otherwise
        :param backend_subnet: models_v2.Subnet object
        """
        pass

    @abc.abstractmethod
    def get_dhcp_ranges(self, context, backend_subnet):
        """Returns DHCP range for a subnet
        :param backend_subnet: models_v2.Subnet object
        """
        pass

    @abc.abstractmethod
    def bind_mac(self, context, backend_subnet, ip_address, mac_address):
        """Binds IP address with MAC.
        :param backend_subnet: models_v2.Subnet object
        :param ip_address: IP address to be bound
        :param mac_address: MAC address to be bound
        """
        pass

    @abc.abstractmethod
    def unbind_mac(self, context, backend_subnet, ip_address):
        """Inverse action for bind_mac.
        :param backend_subnet: models_v2.Subnet object;
        :param ip_address: IP address to be unbound
        """
        pass


@six.add_metaclass(abc.ABCMeta)
class DNSController(neutron_db.NeutronPluginController):
    """Incapsulates DNS related logic"""

    @abc.abstractmethod
    def bind_names(self, context, backend_port):
        """Associate domain name with IP address for a given port
        :param backend_port: models_v2.Port object
        """
        pass

    @abc.abstractmethod
    def unbind_names(self, context, backend_port):
        """Disassociate domain name from a given port
        :param backend_port: models_v2.Port object
        """
        pass

    @abc.abstractmethod
    def create_dns_zones(self, context, backend_subnet):
        """Creates domain name space for a given subnet. This is called on
        subnet creation.
        :param backend_subnet: models_v2.Subnet object
        """
        pass

    @abc.abstractmethod
    def delete_dns_zones(self, context, backend_subnet):
        """Deletes domain name space associated with a subnet. Called on
        delete subnet.
        :param backend_subnet: models_v2.Subnet object
        """
        pass

    @abc.abstractmethod
    def disassociate_floatingip(self, context, floatingip, port_id):
        """Called when floating IP gets disassociated from port
        :param floatingip: l3_db.FloatingIP object to be disassociated
        :param port_id: UUID of a port being disassociated
        """
        pass


@six.add_metaclass(abc.ABCMeta)
class IPAMController(neutron_db.NeutronPluginController):
    """IP address management controller. Operates with higher-level entities
    like networks, subnets and ports
    """

    @abc.abstractmethod
    def create_subnet(self, context, subnet):
        """Creates allocation pools and IP ranges for a subnet.

        :param subnet: user-supplied subnet
        :return models_v2.Subnet object.
        """
        pass

    @abc.abstractmethod
    def update_subnet(self, context, subnet_id, subnet):
        """Called on subnet update.
        :param subnet_id: ID of a subnet being updated
        :param subnet: user-supplied subnet object (dict)
        """
        pass

    @abc.abstractmethod
    def delete_subnet(self, context, subnet):
        """Called on subnet delete. Remove all the higher-level objects
        associated with a subnet
        :param subnet: user-supplied subnet object (dict)
        """
        pass

    @abc.abstractmethod
    def get_subnets(self, context, filters=None, fields=None,
                    sorts=None, limit=None, marker=None,
                    page_reverse=False):
        pass

    @abc.abstractmethod
    def force_off_ports(self, context, ports):
        """Disable ports on subnet delete event
        :param ports: list of models_v2.Port objects to be disabled
        """
        pass

    @abc.abstractmethod
    def get_subnet_by_id(self, context, subnet_id):
        """Returns subnet by UUID
        :param subnet_id: UUID of a subnet
        """
        pass

    @abc.abstractmethod
    def allocate_ip(self, context, backend_subnet, host, ip=None):
        """Allocates IP address based either on a subnet's IP range or an IP
        address provided as an argument
        :param backend_subnet: models_v2.Subnet object
        :param host: port which needs IP generated
        :param ip: IP address to be allocated for a port/host. If not set, IP
        address will be generated from subnet range
        :returns: IP address allocated
        """
        pass

    @abc.abstractmethod
    def deallocate_ip(self, context, backend_subnet, host, ip):
        """Frees IP allocation for a given address
        :param backend_subnet: models_v2.Subnet object
        :param host: host/port which has IP allocated
        :param ip: IP address to be revoked
        """
        pass

    @abc.abstractmethod
    def create_network(self, context, network):
        """Creates network in the database
        :param network: user-supplied network object (dict)
        :returns: models_v2.Network object
        """
        pass

    @abc.abstractmethod
    def delete_network(self, context, network_id):
        """Deletes network from the database
        :param network_id: UUID of a network to be deleted
        """
        pass


@six.add_metaclass(abc.ABCMeta)
class IPAMManager(object):
    """IPAM subsystem manager class which controls IPAM by calling DCHP, DNS
    and IPAM controller methods
    """

    @abc.abstractmethod
    def create_subnet(self, context, subnet):
        """Called on subnet create event
        :param subnet: user-supplied subnet object (dict)
        :returns: models_v2.Subnet object being created
        """
        pass

    @abc.abstractmethod
    def update_subnet(self, context, id, subnet):
        """Called on subnet update event
        :param id: UUID of a subnet being updated
        :param subnet: user-supplied subnet object (dict)
        :returns: updated subnet
        """
        pass

    @abc.abstractmethod
    def delete_subnet(self, context, subnet_id):
        """Called on delete subnet event
        :param subnet_id: UUID of a subnet to be deleted
        """
        pass

    @abc.abstractmethod
    def delete_subnets_by_network(self, context, network_id):
        pass

    @abc.abstractmethod
    def get_subnet_by_id(self, context, subnet_id):
        pass

    @abc.abstractmethod
    def allocate_ip(self, context, host, ip):
        """Called on port create event. Incapsulates logic associated with IP
        allocation process.
        :param host: host/port which needs IP to be allocated
        :param ip: IP address for a port
        """
        pass

    @abc.abstractmethod
    def deallocate_ip(self, context, host, ip):
        """Revoke IP allocated previously
        :param host: host/port to have IP address deallocated
        :param ip: IP address to revoke
        """
        pass

    @abc.abstractmethod
    def get_subnets(self, context, filters=None, fields=None,
                    sorts=None, limit=None, marker=None,
                    page_reverse=False):
        pass

    @abc.abstractmethod
    def create_network(self, context, network):
        """Called on network create event
        :param network: user-supplied network object (dict)
        """
        pass

    @abc.abstractmethod
    def delete_network(self, context, network_id):
        """Called on delete network event
        :param network_id: UUID of network to be deleted
        """
        pass

    @abc.abstractmethod
    def create_port(self, context, port):
        """Called on port create event
        :param port: user-supplied port dict
        """
        pass

    @abc.abstractmethod
    def update_port(self, context, port):
        """Called on port update event
        :param port: user-supplied port dict
        """
        pass

    @abc.abstractmethod
    def delete_port(self, context, port):
        """Called on port delete event
        :param port: user-supplied port dict
        """
        pass

    @abc.abstractmethod
    def associate_floatingip(self, context, floatingip, port):
        """Called on floating IP being associated with a port
        :param floatingip: l3_db.FloatingIP object
        :param port: models_v2.Port to be associated with floating IP
        """
        pass

    @abc.abstractmethod
    def disassociate_floatingip(self, context, floatingip, port_id):
        """Inverse of associate floating IP. Removes relationship between
        floating IP and a port
        :param floatingip: l3_db.FloatingIP object to be disassociated from
        port
        :param port_id: port UUID to be disassociated from floating IP
        """
        pass

    @abc.abstractmethod
    def get_additional_network_dict_params(self, ctx, network_id):
        """Returns a dict of extra arguments for a network. Place your
        implementation if neutron agent(s) require extra information to
        provision DHCP/DNS properly
        :param network_id: UUID of a network to have extra arguments
        """
        pass
