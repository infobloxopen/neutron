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

import re
from oslo.config import cfg as neutron_conf
from taskflow.patterns import linear_flow

from neutron.common import constants as neutron_constants
from neutron.db.infoblox import infoblox_db as infoblox_db
from neutron.common import ipv6_utils
from neutron.ipam.drivers.infoblox import config
from neutron.ipam.drivers.infoblox import connector
from neutron.ipam.drivers.infoblox import constants as ib_constants
from neutron.ipam.drivers.infoblox import ea_manager
from neutron.ipam.drivers.infoblox import exceptions
from neutron.ipam.drivers.infoblox import object_manipulator
from neutron.ipam.drivers.infoblox import tasks
from neutron.ipam.drivers import neutron_ipam
from neutron.openstack.common import log as logging

OPTS = [
    neutron_conf.StrOpt('private_dns_view_name',
                        default=None,
                        help=_("If single_network_view_name is specified, "
                               "this option will define DNS View name used "
                               "to serve networks from the single network "
                               "view. Otherwise it is ignored and "
                               "'default.<netview_name>' is used.")),
    neutron_conf.StrOpt('external_dns_view_name',
                        default=None,
                        help=_("All the subnets created in external networks "
                               "will be associated with DNS View with such "
                               "name. If not specified, name "
                               "'default.<netview_name>' will be used.")),
    neutron_conf.StrOpt('subnet_fqdn_suffix',
                        default='com',
                        help=_("Suffix for subnet domain name. Used to "
                               "generate subnet FQDN which is built using "
                               "the following pattern "
                               "<subnet_domain><subnet_fqdn_suffix>. "
                               "Subnet domain uniquely represents subnet and "
                               "equal to subnet name if specified, otherwise "
                               "equal to the first part of subnet uuid.")),
    neutron_conf.BoolOpt('use_global_dns_zone',
                         default=True,
                         help=_("Use global DNS zone. Global private DNS zone "
                                "only make sense when we use single network "
                                "view")),
    neutron_conf.BoolOpt('allow_admin_network_deletion',
                         default=False,
                         help=_("Allow admin network which is global, "
                                "external, or shared to be deleted"))
]

LOG = logging.getLogger(__name__)
neutron_conf.CONF.register_opts(OPTS)


class InfobloxDNSController(neutron_ipam.NeutronDNSController):

    SUBDOMAIN_NAME_LEN = 8

    def __init__(self, ip_allocator, manipulator=None, config_finder=None):
        super(InfobloxDNSController, self).__init__()

        if not manipulator:
            manipulator = object_manipulator.InfobloxObjectManipulator(
                connector.Infoblox())

        self.infoblox = manipulator
        self.ip_allocator = ip_allocator
        self.config_finder = config_finder
        self.ea_manager = ea_manager.InfobloxEaManager(infoblox_db)
        self.pattern_builder = config.PatternBuilder

    def disassociate_floatingip(self, context, ip_address, port_id):
        floating_port_id = ip_address.get('floating_port_id')
        port = infoblox_db.get_port_by_id(context, floating_port_id)
        extattrs = self.ea_manager.get_extattrs_for_ip(context, port, True)
        self.bind_names(context, port, disassociate=True)

    @staticmethod
    def get_hostname_pattern(port, cfg, instance_name):
        port_owner = port['device_owner']
        if port_owner == neutron_constants.DEVICE_OWNER_FLOATINGIP:
            if instance_name and "{instance_name}" in cfg.hostname_pattern:
                return cfg.hostname_pattern
        if (port_owner
                in ib_constants.NEUTRON_DEVICE_OWNER_TO_PATTERN_MAP.keys()):
            return ib_constants.NEUTRON_DEVICE_OWNER_TO_PATTERN_MAP[port_owner]
        else:
            return cfg.hostname_pattern

    @staticmethod
    def get_instancename(extattrs):
        instance_name = None
        if extattrs:
            vm_attr = extattrs.get('VM Name')
            if vm_attr:
                instance_name = vm_attr.get('value')
        return instance_name

    def _bind_names(self, context, backend_port, binding_func, extattrs=None):
        all_dns_members = []

        for ip in backend_port['fixed_ips']:
            subnet = infoblox_db.get_subnet(context, ip['subnet_id'])
            if subnet['ip_version'] == 4 or \
                    not ipv6_utils.is_auto_address_subnet(subnet):
                cfg = self.config_finder.find_config_for_subnet(context,
                                                                subnet)
                dns_members = cfg.reserve_dns_members()
                all_dns_members.extend(dns_members)
                ip_addr = ip['ip_address']
                instance_name = self.get_instancename(extattrs)

                hostname_pattern = self.get_hostname_pattern(
                                            backend_port, cfg, instance_name)
                pattern_builder = self.pattern_builder(
                                hostname_pattern, cfg.domain_suffix_pattern)
                fqdn = pattern_builder.build(
                    context, subnet, backend_port, ip_addr, instance_name)

                binding_func(cfg.network_view, cfg.dns_view, ip_addr, fqdn,
                             extattrs)

        for member in set(all_dns_members):
            self.infoblox.restart_all_services(member)

    def bind_names(self, context, backend_port, disassociate=False):
        if not backend_port['device_owner']:
            return
        # In the case of disassociating floatingip, we need to explicitly
        # indicate to ignore instance id associated with the floating ip.
        # This is because, at this point, the floating ip is still associated
        # with instance in the neutron database.
        extattrs = self.ea_manager.get_extattrs_for_ip(
                        context, backend_port, ignore_instance_id=disassociate)
        try:
            self._bind_names(context, backend_port,
                             self.ip_allocator.bind_names, extattrs)
        except exceptions.InfobloxCannotCreateObject as e:
            self.unbind_names(context, backend_port)
            raise e

    def unbind_names(self, context, backend_port):
        self._bind_names(context, backend_port, self.ip_allocator.unbind_names)

    def create_dns_zones(self, context, backend_subnet):
        cfg = self.config_finder.find_config_for_subnet(context,
                                                        backend_subnet)
        dns_members = cfg.reserve_dns_members()

        dns_zone = self.pattern_builder(cfg.domain_suffix_pattern).\
            build(context, backend_subnet)
        zone_extattrs = self.ea_manager.get_extattrs_for_zone(
            context, subnet=backend_subnet)

        # Add prefix only for classless networks (ipv4)
        # mask greater than 24 needs prefix.
        # use meaningful prefix if used
        prefix = None
        if backend_subnet['ip_version'] == 4:
            m = re.search(r'/\d+', backend_subnet['cidr'])
            mask = m.group().replace("/", "")
            if int(mask) > 24:
                if len(backend_subnet['name']) > 0:
                    prefix = backend_subnet['name']
                else:
                    prefix = '-'.join(
                        filter(None,
                               re.split(r'[.:/]', backend_subnet['cidr']))
                    )

        args = {
            'backend_subnet': backend_subnet,
            'dnsview_name': cfg.dns_view,
            'fqdn': dns_zone,
            'cidr': backend_subnet['cidr'],
            'prefix': prefix,
            'zone_format': 'IPV%s' % backend_subnet['ip_version'],
            'zone_extattrs': zone_extattrs,
            'obj_manip': self.infoblox
        }
        create_dns_zones_flow = linear_flow.Flow('create-dns-zones')

        if cfg.ns_group:
            args['ns_group'] = cfg.ns_group
            create_dns_zones_flow.add(
                tasks.CreateDNSZonesFromNSGroupTask(),
                tasks.CreateDNSZonesCidrFromNSGroupTask(),
            )
        else:
            args['dns_member'] = dns_members[0]
            args['secondary_dns_members'] = dns_members[1:]
            create_dns_zones_flow.add(
                tasks.CreateDNSZonesTask(),
                tasks.CreateDNSZonesTaskCidr())

        context.store.update(args)
        context.parent_flow.add(create_dns_zones_flow)

    def delete_dns_zones(self, context, backend_subnet):
        cfg = self.config_finder.find_config_for_subnet(context,
                                                        backend_subnet)
        dns_zone_fqdn = self.pattern_builder(cfg.domain_suffix_pattern).\
            build(context, backend_subnet)
        dnsview_name = cfg.dns_view

        network = self._get_network(context, backend_subnet['network_id'])
        is_external = infoblox_db.is_network_external(context,
                                                      network.get('id'))
        is_shared = network.get('shared')

        # If config is global, do not delete dns zone for that subnet
        # If subnet is for external or shared network, do not delete a zone
        #   for the subnet.
        # If subnet is for private network (not external, shared, or global),
        #   check if domain suffix is unique to the subnet.
        #     if subnet name is part of the domain suffix pattern, then delete
        #       forward zone.
        #     if network name is part of the domain suffix pattern, then delete
        #       forward zone only if the subnet is only remaining subnet
        #       in the network.
        # Reverse zone is deleted when not global, not external, and not shared
        if neutron_conf.CONF.allow_admin_network_deletion or \
                not (cfg.is_global_config or is_external or is_shared):
            if (('{subnet_name}' in cfg.domain_suffix_pattern or
                    '{subnet_id}' in cfg.domain_suffix_pattern) or
                (('{network_name}' in cfg.domain_suffix_pattern or
                    '{network_id}' in cfg.domain_suffix_pattern) and
                    infoblox_db.is_last_subnet_in_network(
                        context, backend_subnet['id'],
                        backend_subnet['network_id'])) or
                ('{tenant_id}' in cfg.domain_suffix_pattern and
                    infoblox_db.is_last_subnet_in_tenant(
                        context, backend_subnet['id'],
                        backend_subnet['tenant_id'])) or
                (self._determine_static_zone_deletion(
                    context, backend_subnet,
                    cfg.is_static_domain_suffix))):
                # delete forward zone
                self.infoblox.delete_dns_zone(dnsview_name, dns_zone_fqdn)

            # delete reverse zone
            self.infoblox.delete_dns_zone(dnsview_name,
                                          backend_subnet['cidr'])

    def _determine_static_zone_deletion(self, context,
                                        backend_subnet, is_static):
        """
        Checking config if deletion is possible:
            global tenant
               x     x       n/a
               o     x       cannot delete, global cannot be deleted
               x     o       allow delete, only tenant should use
               o     o       cannot delete, global cannot be deleted
        If possible, then subnet must be the last one among all private
        networks.
        """
        if not is_static:
            return False

        cfgs = self.config_finder.get_all_configs(context, backend_subnet)
        for cfg in cfgs:
            if cfg.is_global_config and cfg.is_static_domain_suffix:
                return False

        return infoblox_db.is_last_subnet_in_private_networks(
            context, backend_subnet['id'])


def has_nameservers(subnet):
    try:
        has_dns = iter(subnet['dns_nameservers']) is not None
    except (TypeError, KeyError):
        has_dns = False

    return has_dns


def get_nameservers(subnet):
    if has_nameservers(subnet):
        return subnet['dns_nameservers']
    return []


def build_fqdn(prefix, zone, ip_address):
    ip_address = ip_address.replace('.', '-')
    if zone:
        zone.lstrip('.')
    return "%(prefix)s%(ip_address)s.%(zone)s" % {
        'prefix': prefix,
        'ip_address': ip_address,
        'zone': zone
    }
