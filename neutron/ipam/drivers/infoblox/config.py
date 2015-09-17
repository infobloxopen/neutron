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
import io
import logging
import operator

from oslo.config import cfg as neutron_conf

from neutron.db.infoblox import infoblox_db as ib_db
from neutron.db.infoblox import models as ib_models
from neutron.ipam.drivers.infoblox import exceptions
from neutron.ipam.drivers.infoblox import nova_manager
from neutron.ipam.drivers.infoblox import objects
from neutron.ipam.drivers.infoblox import keystone_manager
from oslo_serialization import jsonutils

LOG = logging.getLogger(__name__)
OPTS = [
    neutron_conf.StrOpt('conditional_config', default=None,
                        help=_("Infoblox conditional config path")),
    neutron_conf.StrOpt('infoblox_members_config', default=None,
                        help=_("Path to infoblox members config file."))
]

neutron_conf.CONF.register_opts(OPTS)


class ConfigFinder(object):
    """
    _variable_conditions: contains tenant_id, tenant_name or subnet_range "condition"
    _static_conditions: contains global or tenant "condition"
    _assigned_members: contains dhcp members to be registered in db
                       with its mapping id as network view
    """
    VALID_STATIC_CONDITIONS = ['global', 'tenant']
    VALID_VARIABLE_CONDITIONS = ['tenant_id:', 'tenant_name:', 'subnet_range:']
    VALID_CONDITIONS = VALID_STATIC_CONDITIONS + VALID_VARIABLE_CONDITIONS

    def __init__(self, stream=None, member_manager=None):
        """Reads config from `io.IOBase`:stream:. Config is JSON format."""
        self._member_manager = member_manager
        self._variable_conditions = []
        self._static_conditions = []
        self._assigned_members = dict()
        self._is_member_registered = False

        if not member_manager:
            self._member_manager = MemberManager()
        if not stream:
            config_file = neutron_conf.CONF.conditional_config
            if not config_file:
                raise exceptions.InfobloxConfigException(
                    msg="Config not found")
            stream = io.FileIO(config_file)

        with stream:
            try:
                self._conf = jsonutils.loads(stream.read())
                self._read_conditions()
            except ValueError as e:
                raise exceptions.InfobloxConfigException(msg=e)

    def configure_members(self, context):
        # Do this only once after neutron server is restarted
        if self._is_member_registered:
            return

        reg_members = self._member_manager.get_registered_members(
            context)

        # 1. register unregistered members
        # -------------------------------------------------------
        reg_member_names = []
        # if never been registered
        if len(reg_members) > 0:
            reg_member_names = map(operator.attrgetter('name'),
                                   reg_members)
        reg_member_name_set = set(reg_member_names)
        conf_member_name_set = set(
            map(operator.attrgetter('name'),
                self._member_manager.configured_members)
        )
        unreg_member_name_set = conf_member_name_set.difference(
            reg_member_name_set)
        self._member_manager.register_members(context,
                                              list(unreg_member_name_set))

        # 2. reserve the assigned members
        # -------------------------------------------------------
        reserv_member_names = []
        reserv_mapped_ids = []
        if len(reg_members) > 0:
            zip_list = zip(*[(m.name, m.map_id)
                             for m in reg_members if m.map_id])
            if len(zip_list) == 2:
                reserv_member_names = list(zip_list[0])
                reserv_mapped_ids = list(zip_list[1])
        reserv_member_name_set = set(reserv_member_names)

        for netview, memberset in self._assigned_members.items():
            if netview in reserv_mapped_ids:
                continue

            unreserv_member_name_set = memberset.difference(
                reserv_member_name_set)
            if len(unreserv_member_name_set) == 0:
                continue

            member_name = unreserv_member_name_set.pop()
            self._member_manager.reserve_member(context,
                                                netview,
                                                member_name,
                                                ib_models.DHCP_MEMBER_TYPE)
            self._member_manager.reserve_member(context,
                                                netview,
                                                member_name,
                                                ib_models.DNS_MEMBER_TYPE)

        self._is_member_registered = True

    def find_config_for_subnet(self, context, subnet):
        """
        Returns first configuration which matches the object being created.
        :param context:
        :param subnet:
        :return: :raise exceptions.InfobloxConfigException:
        """
        if not self._is_member_registered:
            self.configure_members(context)

        # First search for matching variable condition
        for conditions in [self._variable_conditions, self._static_conditions]:
            for cfg in conditions:
                cfg = Config(cfg, context, subnet, self._member_manager)
                if self._condition_matches(context, cfg, subnet):
                    return cfg

        raise exceptions.InfobloxConfigException(
            msg="No config found for subnet %s" % subnet)

    def get_all_configs(self, context, subnet):
        cfgs = []
        for conditions in [self._variable_conditions, self._static_conditions]:
            for cfg in conditions:
                cfg = Config(cfg, context, subnet, self._member_manager)
                cfgs.append(cfg)
        return cfgs

    @staticmethod
    def _variable_condition_match(condition, var, expected):
        return (condition.startswith(var) and
                condition.split(':')[1] == expected)

    def _condition_matches(self, context, config, subnet):
        net_id = subnet.get('network_id', subnet.get('id'))
        cidr = subnet.get('cidr')
        tenant_id = subnet['tenant_id']
        tenant_name = keystone_manager.get_tenant_name_by_id(subnet['tenant_id'])

        is_external = ib_db.is_network_external(context, net_id)
        cond = config.condition
        condition_matches = (
            cond == 'global' or cond == 'tenant' or
            self._variable_condition_match(cond, 'tenant_id', tenant_id) or
            self._variable_condition_match(cond, 'tenant_name', tenant_name) or
            self._variable_condition_match(cond, 'subnet_range', cidr))

        return config.is_external == is_external and condition_matches

    def _read_conditions(self):
        # Define lambdas to check
        is_static_cond = lambda cond, static_conds: cond in static_conds
        is_var_cond = lambda cond, var_conds: any([cond.startswith(valid)
                                                  for valid in var_conds])

        for conf in self._conf:
            # If condition contain colon: validate it as variable
            if ':' in conf['condition'] and\
                is_var_cond(conf['condition'],
                            self.VALID_VARIABLE_CONDITIONS):
                self._variable_conditions.append(conf)
            # If not: validate it as static
            elif is_static_cond(conf['condition'],
                                self.VALID_STATIC_CONDITIONS):
                self._static_conditions.append(conf)
            # If any of previous checker cannot validate value - rise error
            else:
                msg = 'Invalid condition specified: {0}'.format(
                      conf['condition'])
                raise exceptions.InfobloxConfigException(msg=msg)

            # Look for assigned member; if dhcp_members list specific
            # members, then network_view should be static as well
            netview = conf.get('network_view', 'default')
            members = conf.get('dhcp_members', Config.NEXT_AVAILABLE_MEMBER)
            if not isinstance(members, list) and \
                    members != Config.NEXT_AVAILABLE_MEMBER:
                members = [members]
            if isinstance(members, list) and \
                    not netview.startswith('{'):
                if self._assigned_members.get(netview):
                    self._assigned_members[netview].update(set(members))
                else:
                    self._assigned_members[netview] = set(members)


class PatternBuilder(object):
    def __init__(self, *pattern):
        self.pattern = '.'.join([el.strip('.')
                                 for el in pattern if el is not None])

    def build(self, context, subnet, port=None, ip_addr=None, instance_name=None):
        """
        Builds string by passing supplied values into pattern
        :raise exceptions.InfobloxConfigException:
        """
        self._validate_pattern()

        subnet_name = subnet['name'] if subnet['name'] else subnet['id']

        pattern_dict = {
            'network_id': subnet['network_id'],
            'network_name': ib_db.get_network_name(context, subnet),
            'tenant_id': subnet['tenant_id'],
            'tenant_name': keystone_manager.get_tenant_name_by_id(subnet['tenant_id']),
            'subnet_name': subnet_name,
            'subnet_id': subnet['id'],
            'user_id': context.user_id
        }

        if ip_addr:
            octets = ip_addr.split('.')
            ip_addr = ip_addr.replace('.', '-').replace(':', '-')
            pattern_dict['ip_address'] = ip_addr
            for i in xrange(len(octets)):
                octet_key = 'ip_address_octet{i}'.format(i=(i + 1))
                pattern_dict[octet_key] = octets[i]

        if port:
            pattern_dict['port_id'] = port['id']
            pattern_dict['instance_id'] = port['device_id']
            if instance_name:
                pattern_dict['instance_name'] = instance_name
            else:
                if '{instance_name}' in self.pattern:
                    nm = nova_manager.NovaManager()
                    pattern_dict['instance_name'] = nm.get_instance_name_by_id(
                        port['device_id'])

        try:
            fqdn = self.pattern.format(**pattern_dict)
        except (KeyError, IndexError) as e:
            raise exceptions.InfobloxConfigException(
                msg="Invalid pattern %s" % e)

        return fqdn

    def _validate_pattern(self):
        invalid_values = ['..']
        for val in invalid_values:
            if val in self.pattern:
                error_message = "Invalid pattern value {0}".format(val)
                raise exceptions.InfobloxConfigException(msg=error_message)


class Config(object):
    NEXT_AVAILABLE_MEMBER = '<next-available-member>'
    NETWORK_VIEW_TEMPLATES = ['{tenant_id}',
                              '{tenant_name}',
                              '{network_name}',
                              '{network_id}']

    DEFINING_ATTRS = ['condition', '_dhcp_members', '_dns_members',
                      '_net_view', '_dns_view']

    def __init__(self, config_dict, context, subnet,
                 member_manager=None):
        if not member_manager:
            _member_manager = MemberManager()

        if 'condition' not in config_dict:
            raise exceptions.InfobloxConfigException(
                msg="Missing mandatory 'condition' config option")

        self.condition = config_dict['condition']
        self.is_external = config_dict.get('is_external', False)

        self._net_view = config_dict.get('network_view', 'default')
        self._set_network_view_scope()

        self._dns_view = config_dict.get('dns_view', 'default')

        self.require_dhcp_relay = config_dict.get('require_dhcp_relay', False)

        self._dhcp_members = self._members_identifier(
            config_dict.get('dhcp_members', self.NEXT_AVAILABLE_MEMBER))
        self._dns_members = self._members_identifier(
            config_dict.get('dns_members', self._dhcp_members))

        self.domain_suffix_pattern = config_dict.get(
            'domain_suffix_pattern', 'global.com')
        self.hostname_pattern = config_dict.get(
            'hostname_pattern', 'host-{ip_address}.{subnet_name}')

        pattern = re.compile(r'\{\S+\}')
        if pattern.findall(self.domain_suffix_pattern):
            self.is_static_domain_suffix = False
        else:
            self.is_static_domain_suffix = True

        self.network_template = config_dict.get('network_template')
        self.ns_group = config_dict.get('ns_group')

        self.context = context
        self.subnet = subnet
        self._member_manager = member_manager

    def __eq__(self, other):
        return (isinstance(other, self.__class__) and
                all(map(lambda attr:
                        getattr(self, attr) == getattr(other, attr),
                        self.DEFINING_ATTRS)))

    def __hash__(self):
        return hash(tuple(self.DEFINING_ATTRS))

    def __repr__(self):
        values = {
            'condition': self.condition,
            'dns_members': self._dns_members,
            'dhcp_members': self._dhcp_members,
            'net_view': self._net_view,
            'dns_view': self._dns_view
        }

        return "ConditionalConfig{0}".format(values)

    @property
    def network_view_scope(self):
        return self._net_view_scope

    @property
    def network_view(self):
        if self._net_view_scope == 'tenant_id':
            return self.subnet['tenant_id']
        if self._net_view_scope == 'tenant_name':
            return keystone_manager.get_tenant_name_by_id(self.subnet['tenant_id'])
        if self._net_view_scope == 'network_name':
            return ib_db.get_network_name(self.context, self.subnet)
        if self._net_view_scope == 'network_id':
            return self.subnet['network_id']
        return self._net_view

    @property
    def dns_view(self):
        if self.network_view == 'default':
            return self._dns_view

        return '.'.join([self._dns_view, self.network_view])

    @property
    def dhcp_members(self):
        return self._get_members(ib_models.DHCP_MEMBER_TYPE)

    @property
    def dns_members(self):
        return self._get_members(ib_models.DNS_MEMBER_TYPE)

    @property
    def is_global_config(self):
        return self.condition == 'global'

    def reserve_dns_members(self):
        reserved_members = self._reserve_members(self._dns_members,
                                                 self.ns_group,
                                                 ib_models.DNS_MEMBER_TYPE)

        if isinstance(reserved_members, list):
            return reserved_members
        elif reserved_members:
            return [reserved_members]
        else:
            return []

    def reserve_dhcp_members(self):
        reserved_members = self._reserve_members(self._dhcp_members,
                                                 self.network_template,
                                                 ib_models.DHCP_MEMBER_TYPE)

        if isinstance(reserved_members, list):
            return reserved_members
        else:
            return [reserved_members]

    def release_member(self, map_id):
        self._member_manager.release_member(self.context, map_id)

    def requires_net_view(self):
        return True

    def verify_subnet_update_is_allowed(self, subnet_new):
        """
        Subnet update procedure is not allowed if Infoblox zone name exists on
        NIOS. This can only happen if domain suffix pattern has subnet name
        included.
        """
        subnet_new_name = subnet_new.get('name')
        subnet_name = self.subnet.get('name')
        pattern = self.domain_suffix_pattern
        update_allowed = not (subnet_name is not None and
                              subnet_new_name is not None and
                              subnet_name != subnet_new_name and
                              '{subnet_name}' in pattern)

        if not update_allowed:
            raise exceptions.OperationNotAllowed(
                reason="subnet_name is in domain name pattern")

        if subnet_new.get('network') and subnet_new.get('network_before'):
            network_new_name = subnet_new.get('network').get('name')
            network_name = subnet_new.get('network_before').get('name')
            update_allowed = not (network_name is not None and
                                  network_new_name is not None and
                                  network_name != network_new_name and
                                  '{network_name}' in pattern)

            if not update_allowed:
                raise exceptions.OperationNotAllowed(
                    reason="network_name is in domain name pattern")

    def _set_network_view_scope(self):
        if (self._net_view.startswith('{') and
                self._net_view not in self.NETWORK_VIEW_TEMPLATES):
            raise exceptions.InfobloxConfigException(
                msg="Invalid config value for 'network_view'")

        if self._net_view == '{tenant_id}':
            self._net_view_scope = 'tenant_id'
        if self._net_view == '{tenant_name}':
            self._net_view_scope = 'tenant_name'
        elif self._net_view == '{network_name}':
            self._net_view_scope = 'network_name'
        elif self._net_view == '{network_id}':
            self._net_view_scope = 'network_id'
        else:
            self._net_view_scope = 'static'

    def _get_members(self, member_type):
        members = self._member_manager.find_members(self.context,
                                                    self.network_view,
                                                    member_type)
        if members:
            return members

        msg = ("Looks like you're trying to call config.{member_type}_member "
               "without reserving one. You should call "
               "reserve_{member_type}_member() "
               "first!".format(member_type=member_type))
        raise RuntimeError(msg)

    def _reserve_members_list(self, assigned_members, member_type):
        members_to_reserve = [self._member_manager.get_member(member)
                              for member in assigned_members]
        for member in members_to_reserve:
            self._member_manager.reserve_member(self.context,
                                                self.network_view,
                                                member.name,
                                                member_type)
        return members_to_reserve

    def _reserve_by_template(self, assigned_members, template, member_type):
        member = self._get_member_from_template(assigned_members, template)
        self._member_manager.reserve_member(self.context,
                                            self.network_view,
                                            member.name,
                                            member_type)
        return member

    def _reserve_next_avaliable(self, member_type):
        member = self._member_manager.next_available(self.context,
                                                     member_type)
        self._member_manager.reserve_member(self.context,
                                            self.network_view,
                                            member.name,
                                            member_type)
        return member

    def _reserve_members(self, assigned_members, template, member_type):
        members = self._member_manager.find_members(self.context,
                                                    self.network_view,
                                                    member_type)
        if members:
            return members

        if assigned_members == self.NEXT_AVAILABLE_MEMBER:
            return self._reserve_next_avaliable(member_type)
        elif isinstance(assigned_members, list):
            return self._reserve_members_list(assigned_members,
                                              member_type)
        elif template:
            return self._reserve_by_template(assigned_members,
                                             template,
                                             member_type)

    def _get_member_from_template(self, assigned_members, template):
        member_defined = (assigned_members != self.NEXT_AVAILABLE_MEMBER
                          and isinstance(assigned_members, basestring))
        if template and not member_defined:
            msg = 'Member MUST be configured for {template}'.format(
                template=template)
            raise exceptions.InfobloxConfigException(msg=msg)
        return self._member_manager.get_member(assigned_members)

    def _members_identifier(self, members):
        if not isinstance(members, list) and \
                members != self.NEXT_AVAILABLE_MEMBER:
            members = [members]
        return members


class MemberManager(object):
    def __init__(self, member_config_stream=None):
        if not member_config_stream:
            config_file = neutron_conf.CONF.infoblox_members_config
            if not config_file:
                raise exceptions.InfobloxConfigException(
                    msg="Config not found")
            member_config_stream = io.FileIO(config_file)

        with member_config_stream:
            all_members = jsonutils.loads(member_config_stream.read())

            try:
                self.configured_members = map(
                    lambda m: objects.Member(name=m.get('name'),
                                             ip=m.get('ipv4addr'),
                                             ipv6=m.get('ipv6addr'),
                                             delegate=m.get('delegate'),
                                             map_id=None),
                    filter(lambda m: m.get('is_available', True),
                           all_members))
            except KeyError as key:
                raise exceptions.InfobloxConfigException(
                    msg="Invalid member config key: %s" % key)

        if self.configured_members is None or \
                len(self.configured_members) == 0:
            raise exceptions.InfobloxConfigException(
                msg="Configured member not found")

    def __repr__(self):
        values = {
            'configured_members': self.configured_members
        }
        return "MemberManager{0}".format(values)

    def register_members(self, context, member_names):
        for member_name in member_names:
            ib_db.register_member(context, None, member_name,
                                  ib_models.DHCP_MEMBER_TYPE)
            ib_db.register_member(context, None, member_name,
                                  ib_models.DNS_MEMBER_TYPE)

    def get_registered_members(self, context,
                               member_type=ib_models.DHCP_MEMBER_TYPE):
        registered_members = ib_db.get_registered_members(context,
                                                          member_type)
        members = []
        for reg_member in registered_members:
            for member in self.configured_members:
                if member.name == reg_member.member_name:
                    member.map_id = reg_member.map_id
                    members.append(member)
        return members

    def next_available(self, context, member_type):
        avail_member = ib_db.get_available_member(context, member_type)
        if not avail_member:
            raise exceptions.InfobloxConfigException(
                msg="No infoblox member available")

        return self.get_member(avail_member.member_name)

    def reserve_member(self, context, mapping, member_name, member_type):
        ib_db.attach_member(context, mapping, member_name, member_type)

    def release_member(self, context, mapping):
        ib_db.release_member(context, mapping)

    def get_member(self, member_name):
        for member in self.configured_members:
            if member.name == member_name:
                return member
        raise exceptions.InfobloxConfigException(
            msg="No infoblox member available")

    def find_members(self, context, map_id, member_type):
        existing_members = ib_db.get_members(context, map_id, member_type)
        if not existing_members:
            return []

        members = []
        for existing_member in existing_members:
            for member in self.configured_members:
                if member.name == existing_member.member_name:
                    members.append(member)

        if not members:
            msg = "Reserved member not available in config"
            raise exceptions.InfobloxConfigException(msg=msg)

        return members
