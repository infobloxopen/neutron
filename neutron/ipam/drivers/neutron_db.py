# Copyright (c) 2014 OpenStack Foundation.
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
import netaddr

from sqlalchemy import orm
from sqlalchemy.orm import exc

from neutron.common import exceptions as n_exc
from neutron.db import common_db_mixin
from neutron.db import models_v2
from neutron.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class NeutronPluginController(common_db_mixin.CommonDbMixin):
    def _get_network(self, context, net_id):
        try:
            network = self._get_by_id(context, models_v2.Network, net_id)
        except exc.NoResultFound:
            raise n_exc.NetworkNotFound(net_id=net_id)
        return network

    def _get_subnet(self, context, subnet_id):
        try:
            subnet = self._get_by_id(context, models_v2.Subnet, subnet_id)
        except exc.NoResultFound:
            raise n_exc.SubnetNotFound(subnet_id=subnet_id)
        return subnet


def get_subnets_by_port_id(context, port_id):
    subnets_with_port = []
    # Get Requested port
    port = context.session.query(models_v2.Port).filter_by(id=port_id).one()
    # Collect all subnets from port network
    subnets = get_subnets_by_network(context, port.network_id)
    for sub in subnets:
        # Collect all ports from subnet
        subnet_ports = get_subnet_ports(context, sub.id)
        # Compare them with original port, and if they are the same - save
        subnets_with_port += [sub for sp in subnet_ports if sp.id == port.id]

    return subnets_with_port


def get_subnet_ports(context, subnet_id):
    # Check if any tenant owned ports are using this subnet
    ports_qry = context.session.query(models_v2.Port).join(
        models_v2.IPAllocation).with_lockmode(
        'update').enable_eagerloads(False)
    ports = ports_qry.filter_by(subnet_id=subnet_id)
    return ports


def get_all_subnets(context):
    return context.session.query(models_v2.Subnet).all()


def generate_ip(context, subnet):
    try:
        return _try_generate_ip(context, subnet)
    except n_exc.IpAddressGenerationFailure:
        _rebuild_availability_ranges(context, subnet)

    return _try_generate_ip(context, subnet)


def allocate_specific_ip(context, subnet_id, ip_address):
    """Allocate a specific IP address on the subnet."""
    ip = int(netaddr.IPAddress(ip_address))
    range_qry = context.session.query(
        models_v2.IPAvailabilityRange).join(
            models_v2.IPAllocationPool).with_lockmode('update')
    results = range_qry.filter_by(subnet_id=subnet_id)
    for range in results:
        first = int(netaddr.IPAddress(range['first_ip']))
        last = int(netaddr.IPAddress(range['last_ip']))
        if first <= ip <= last:
            if first == last:
                context.session.delete(range)
                return
            elif first == ip:
                range['first_ip'] = str(netaddr.IPAddress(ip_address) + 1)
                return
            elif last == ip:
                range['last_ip'] = str(netaddr.IPAddress(ip_address) - 1)
                return
            else:
                # Split into two ranges
                new_first = str(netaddr.IPAddress(ip_address) + 1)
                new_last = range['last_ip']
                range['last_ip'] = str(netaddr.IPAddress(ip_address) - 1)
                ip_range = models_v2.IPAvailabilityRange(
                    allocation_pool_id=range['allocation_pool_id'],
                    first_ip=new_first,
                    last_ip=new_last)
                context.session.add(ip_range)
                return ip_address
        return None


def get_dns_by_subnet(context, subnet_id):
    dns_qry = context.session.query(models_v2.DNSNameServer)
    return dns_qry.filter_by(subnet_id=subnet_id).all()


def get_route_by_subnet(context, subnet_id):
    route_qry = context.session.query(models_v2.SubnetRoute)
    return route_qry.filter_by(subnet_id=subnet_id).all()


def get_subnets_by_network(context, network_id):
    subnet_qry = context.session.query(models_v2.Subnet)
    return subnet_qry.filter_by(network_id=network_id).all()


def _try_generate_ip(context, subnet):
    """Generate an IP address.

    The IP address will be generated from one of the subnets defined on
    the network.
    """
    if type(subnet) is list:
        subnet = subnet[0]
    range_qry = context.session.query(
        models_v2.IPAvailabilityRange).join(
            models_v2.IPAllocationPool).with_lockmode('update')
    range = range_qry.filter_by(subnet_id=subnet.id).first()
    if not range:
        LOG.debug(_("All IPs from subnet %(subnet_id)s (%(cidr)s) "
                    "allocated"),
                  {'subnet_id': subnet.id,
                   'cidr': subnet.cidr})
        raise n_exc.IpAddressGenerationFailure(
            net_id=subnet['network_id'])
    ip_address = range['first_ip']
    LOG.debug(_("Allocated IP - %(ip_address)s from %(first_ip)s "
                "to %(last_ip)s"),
              {'ip_address': ip_address,
               'first_ip': range['first_ip'],
               'last_ip': range['last_ip']})
    if range['first_ip'] == range['last_ip']:
        # No more free indices on subnet => delete
        LOG.debug(_("No more free IP's in slice. Deleting allocation "
                    "pool."))
        context.session.delete(range)
    else:
        # increment the first free
        range['first_ip'] = str(netaddr.IPAddress(ip_address) + 1)
    return {'ip_address': ip_address, 'subnet_id': subnet.id}


def _rebuild_availability_ranges(context, subnets):
    """Rebuild availability ranges.

    This method is called only when there's no more IP available or by
    _update_subnet_allocation_pools. Calling
    _update_subnet_allocation_pools before calling this function deletes
    the IPAllocationPools associated with the subnet that is updating,
    which will result in deleting the IPAvailabilityRange too.
    """
    ip_qry = context.session.query(
        models_v2.IPAllocation).with_lockmode('update')
    # PostgreSQL does not support select...for update with an outer join.
    # No join is needed here.
    pool_qry = context.session.query(
        models_v2.IPAllocationPool).options(
            orm.noload('available_ranges')).with_lockmode('update')
    for subnet in sorted(subnets):
        LOG.debug(_("Rebuilding availability ranges for subnet %s")
                  % subnet)

        # Create a set of all currently allocated addresses
        ip_qry_results = ip_qry.filter_by(subnet_id=subnet['id'])
        allocations = netaddr.IPSet([netaddr.IPAddress(i['ip_address'])
                                    for i in ip_qry_results])

        for pool in pool_qry.filter_by(subnet_id=subnet['id']):
            # Create a set of all addresses in the pool
            poolset = netaddr.IPSet(netaddr.iter_iprange(pool['first_ip'],
                                                         pool['last_ip']))

            # Use set difference to find free addresses in the pool
            available = poolset - allocations

            # Generator compacts an ip set into contiguous ranges
            def ipset_to_ranges(ipset):
                first, last = None, None
                for cidr in ipset.iter_cidrs():
                    if last and last + 1 != cidr.first:
                        yield netaddr.IPRange(first, last)
                        first = None
                    first, last = first if first else cidr.first, cidr.last
                if first:
                    yield netaddr.IPRange(first, last)

            # Write the ranges to the db
            for ip_range in ipset_to_ranges(available):
                available_range = models_v2.IPAvailabilityRange(
                    allocation_pool_id=pool['id'],
                    first_ip=str(netaddr.IPAddress(ip_range.first)),
                    last_ip=str(netaddr.IPAddress(ip_range.last)))
                context.session.add(available_range)
