# Copyright 2014 OpenStack Foundation
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
import os
import random

import netaddr
from oslo.config import cfg

from neutron.agent.linux import dhcp
from neutron.agent.linux import ip_lib
from neutron.agent.linux import utils
from neutron.common import exceptions as exc
from neutron.common import ipv6_utils
from oslo_log import log as logging
from neutron.openstack.common import uuidutils

LOG = logging.getLogger(__name__)

OPTS = [
    cfg.ListOpt('external_dhcp_servers',
                default=None,
                help=_('IP addresses of DHCP servers to relay to.')),
    cfg.ListOpt('external_dns_servers',
                default=None,
                help=_('IP addresses of DNS servers to relay to.')),
    cfg.StrOpt('dhcp_relay_bridge',
               default=None,
               help=_('Name of a bridge through which ipam proxy agent will'
                      ' connect to external network in which DHCP and DNS'
                      ' server resides.')),
    cfg.StrOpt('dhclient_path',
               default='dhclient',
               help=_('Path to dhclient executable.')),
    cfg.StrOpt('dhcrelay_path',
               default='dhcrelay',
               help=_('Path to dhcrelay executable.')),
    cfg.BoolOpt('use_link_selection_option',
                default=True,
                help=_('Run dhcrelay with -o flag.')),
    cfg.BoolOpt('use_ipv6_unicast_requests',
                default=True,
                help=_('Run dhcrelay -u server1%iface2 -u server2%iface2')),
    cfg.StrOpt('dhcp_relay_management_network',
               default=None,
               help=_("CIDR for the management network served by "
                      "Infoblox DHCP member")),
    cfg.BoolOpt('enable_ipv6_relay',
                default=True,
                help=_('Enable/Disable DHCP/DNS relay for IPv6'))
]


MGMT_INTERFACE_IP_ATTR = 'mgmt_iface_ip'


def _generate_mac_address():
    mac = [0x00, 0x16, 0x3e,
           random.randint(0x00, 0x7f),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]
    return ':'.join(map(lambda x: "%02x" % x, mac))


class DhcpDnsProxy(dhcp.DhcpLocalProcess):
    """DHCP & DNS relay agent class."""

    MINIMUM_VERSION = 0
    DEV_NAME_LEN = 14
    RELAY_DEV_NAME_PREFIX = 'trel'
    NEUTRON_NETWORK_ID_KEY = 'NEUTRON_NETWORK_ID'
    DHCPv4 = 4
    DHCPv6 = 6

    def _calc_dev_name_len(self):
        if self.conf.interface_dev_name_len:
            return self.conf.interface_dev_name_len
        else:
            return self.DEV_NAME_LEN

    def _enable_dns_dhcp(self):
        """check if there is a subnet within the network with dhcp enabled."""
        for subnet in self.network.subnets:
            if subnet.enable_dhcp:
                return True
        return False

    def __init__(self, conf, network, root_helper='sudo',
                 version=None, plugin=None):
        super(DhcpDnsProxy, self).__init__(conf, network, root_helper,
                                           version, plugin)

        external_dhcp_servers = self._get_relay_ips('external_dhcp_servers')
        external_dns_servers = self._get_relay_ips('external_dns_servers')
        required_options = {'dhcp_relay_bridge': self.conf.dhcp_relay_bridge,
                            'external_dhcp_servers': external_dhcp_servers,
                            'external_dns_servers': external_dns_servers}

        for option_name, option in required_options.iteritems():
            if not option:
                LOG.error(_('You must specify an %(opt)s option in config'),
                          {'opt': option_name})
                raise exc.InvalidConfigurationOption(
                    opt_name=option_name,
                    opt_value=option
                )

        self.dev_name_len = self._calc_dev_name_len()
        self.device_manager = DnsDhcpProxyDeviceManager(
            conf, root_helper, plugin)

    @classmethod
    def check_version(cls):
        return 0

    @classmethod
    def get_isolated_subnets(cls, network):
        """Returns a dict indicating whether or not a subnet is isolated"""
        if hasattr(dhcp.Dnsmasq, 'get_isolated_subnets') \
               and callable(getattr(dhcp.Dnsmasq, 'get_isolated_subnets')):
            dhcp.Dnsmasq.get_isolated_subnets(network)

    @classmethod
    def should_enable_metadata(cls, conf, network):
        """True if the metadata-proxy should be enabled for the network."""
        if hasattr(dhcp.Dnsmasq, 'should_enable_metadata') \
               and callable(getattr(dhcp.Dnsmasq, 'should_enable_metadata')):
            dhcp.Dnsmasq.should_enable_metadata(conf, network)
        else:
            conf.enable_isolated_metadata

    @classmethod
    def existing_dhcp_networks(cls, conf, root_helper):
        """Return a list of existing networks ids that we have configs for."""
        confs_dir = os.path.abspath(os.path.normpath(conf.dhcp_confs))
        return [
            c for c in os.listdir(confs_dir)
            if uuidutils.is_uuid_like(c)
        ]

    def release_lease(self, mac_address, removed_ips):
        """Release a DHCP lease."""
        pass

    def reload_allocations(self):
        """Force the DHCP server to reload the assignment database."""
        pass

    @property
    def ipv6_enabled(self):
        return self.conf.enable_ipv6_relay and ipv6_utils.is_enabled()

    def get_dhcp_pid(self, version):
        """Last known pid for the dhcrelay process spawned for this network."""
        return self._get_value_from_conf_file('dhcp%s_pid' % version, int)

    def get_dns_pid(self):
        """Last known pid for the dnsmasq process spawned for this network."""
        return self._get_value_from_conf_file('dns_pid', int)

    def is_dhcrelay_pid(self, pid):
        pid_path = '/proc/%s/cmdline' % pid
        if (pid and os.path.isdir('/proc/%s/' % pid) and
            self.conf.dhcrelay_path in open(pid_path).read()):
            return True
        return False

    def is_dhcp_active(self):
        """Is any dhcprelay still active"""
        pids = [self.get_dhcp_pid(version=DhcpDnsProxy.DHCPv4)]
        if self.ipv6_enabled:
            pids.append(self.get_dhcp_pid(version=DhcpDnsProxy.DHCPv6))

        if not any(pids):
            return False

        for pid in pids:
            if self.is_dhcrelay_pid(pid):
                return True
        return False

    def is_dns_active(self):
        pid = self.get_dns_pid()
        if not pid:
            return False
        return os.path.isdir('/proc/%s/' % pid)

    def enable(self):
        relay_iface_name = self._get_relay_device_name()
        relay_iface_mac_address = _generate_mac_address()
        self.device_manager.setup_relay(
            self.network,
            relay_iface_name,
            relay_iface_mac_address,
            self.conf.dhcp_relay_bridge)

        interface_name = self.device_manager.setup(self.network)
        if self.is_dhcp_active() or self.is_dns_active():
            self.restart()
        elif self._enable_dns_dhcp():
            self.interface_name = interface_name
            self.spawn_process()

    def disable(self, retain_port=False):
        def kill_proc(pid):
            if not pid:
                return
            cmd = ['kill', '-9', pid]
            utils.execute(cmd, self.root_helper)

        def check_dhcp_pid():
            if self.ipv6_enabled:
                return self.get_dhcp_pid(DhcpDnsProxy.DHCPv4) and \
                    self.get_dhcp_pid(DhcpDnsProxy.DHCPv6)
            else:
                return self.get_dhcp_pid(DhcpDnsProxy.DHCPv4)

        def log_dhcp_pid_info():
            if self.ipv6_enabled:
                LOG.debug(
                _('dhcrelay for %(net_id)s, dhcp_pid %(dhcp_pid)d, '
                  'dhcp6_pid %(dhcp6_pid)d, is stale, ignoring command'),
                {
                    'net_id': self.network.id,
                    'dhcp_pid': self.get_dhcp_pid(DhcpDnsProxy.DHCPv4),
                    'dhcp6_pid': self.get_dhcp_pid(DhcpDnsProxy.DHCPv6)
                })
            else:
                LOG.debug(
                _('dhcrelay for %(net_id)s, dhcp_pid %(dhcp_pid)d '
                  'is stale, ignoring command'),
                {
                    'net_id': self.network.id,
                    'dhcp_pid': self.get_dhcp_pid(DhcpDnsProxy.DHCPv4)
                })

        if self.is_dhcp_active():
            kill_proc(self.get_dhcp_pid(DhcpDnsProxy.DHCPv4))
            if self.ipv6_enabled:
                kill_proc(self.get_dhcp_pid(DhcpDnsProxy.DHCPv6))
        elif check_dhcp_pid():
            log_dhcp_pid_info()
        else:
            LOG.debug(_('No dhcrelay started for %s'), self.network.id)

        if self.is_dns_active():
            kill_proc(self.get_dns_pid())
        elif self.get_dns_pid():
            LOG.debug(_('dnsmasq for %(net_id)s, dhcp_pid %(dns_pid)d, is'
                        ' stale, ignoring command'),
                      {'net_id': self.network.id,
                       'dns_pid': self.get_dns_pid()}
                      )
        else:
            LOG.debug(_('No dnsmasq started for %s'), self.network.id)

        if not retain_port:
            self.device_manager.destroy(self.network, self.interface_name)
            self.device_manager.destroy_relay(
                self.network,
                self._get_relay_device_name(),
                self.conf.dhcp_relay_bridge)

            if self.conf.dhcp_delete_namespaces and self.network.namespace:
                ns_ip = ip_lib.IPWrapper(self.root_helper,
                                         self.network.namespace)
                try:
                    ns_ip.netns.delete(self.network.namespace)
                except RuntimeError:
                    msg = _('Failed trying to delete namespace: %s')
                    LOG.exception(msg, self.network.namespace)
        self._remove_config_files()

    def spawn_process(self):
        """Spawns a IPAM proxy processes for the network."""
        self._spawn_dhcp_proxy()
        self._spawn_dns_proxy()

    def _construct_dhcrelay_commands(self, relay_ips, relay_ipv6s):
        dhcrelay_v4_command = [
            self.conf.dhcrelay_path, '-4', '-a',
            '-pf', self.get_conf_file_name('dhcp4_pid', ensure_conf_dir=True),
            '-i', self.interface_name]

        ipv6_ok = self.ipv6_enabled
        if ipv6_ok:
            dhcrelay_v6_command = [
                self.conf.dhcrelay_path, '-6', '-I',
                '-pf', self.get_conf_file_name('dhcp6_pid', ensure_conf_dir=True),
                '-l', self.interface_name]

        if self.conf.use_link_selection_option:
            # dhcrelay -4 -a -i iface1 -l iface2 server1 server2
            dhcrelay_v4_command.append('-o')
            dhcrelay_v4_command.append(self._get_relay_device_name())

            if ipv6_ok:
                # dhcrelay -6 -l iface1 -u server1%iface2 -u server2%iface2
                if relay_ipv6s:
                    for ipv6_addr in relay_ipv6s:
                        dhcrelay_v6_command.append('-u')

                        if self.conf.use_ipv6_unicast_requests:
                            dhcrelay_v6_command.append("%".join((
                                ipv6_addr, self._get_relay_device_name())))
                        else:
                            dhcrelay_v6_command.append(
                                self._get_relay_device_name())

        dhcrelay_v4_command.append(" ".join(relay_ips))

        if ipv6_ok:
            return [
                dhcrelay_v4_command,
                dhcrelay_v6_command
            ]
        else:
            return [
                dhcrelay_v4_command
            ]

    def _spawn_dhcp_proxy(self):
        """Spawns a dhcrelay process for the network."""
        relay_ips = self._get_relay_ips('external_dhcp_servers')
        relay_ipv6s = self._get_relay_ips('external_dhcp_ipv6_servers')

        if not relay_ips:
            LOG.error(_('DHCP relay server isn\'t defined for network %s'),
                      self.network.id)
            return

        commands = self._construct_dhcrelay_commands(relay_ips, relay_ipv6s)

        for cmd in commands:
            if self.network.namespace:
                ip_wrapper = ip_lib.IPWrapper(self.root_helper,
                                              self.network.namespace)
                try:
                    ip_wrapper.netns.execute(cmd)
                except RuntimeError:
                    LOG.info(_("Can't start dhcrelay for %(command)s"),
                             {'command': cmd})
            else:
                utils.execute(cmd, self.root_helper)

    def _spawn_dns_proxy(self):
        """Spawns a Dnsmasq process in DNS relay only mode for the network."""
        relay_ips = self._get_relay_ips('external_dns_servers')

        if not relay_ips:
            LOG.error(_('DNS relay server isn\'t defined for network %s'),
                      self.network.id)
            return

        server_list = []
        for relay_ip in relay_ips:
            server_list.append("--server=%s" % relay_ip)

        env = {
            self.NEUTRON_NETWORK_ID_KEY: self.network.id,
        }

        cmd = [
            'dnsmasq',
            '--no-hosts',
            '--no-resolv',
            '--strict-order',
            '--bind-interfaces',
            '--interface=%s' % self.interface_name,
            '--except-interface=lo',
            '--all-servers']
        cmd += server_list
        cmd += ['--pid-file=%s' % self.get_conf_file_name(
                'dns_pid', ensure_conf_dir=True)]

        if self.network.namespace:
            ip_wrapper = ip_lib.IPWrapper(self.root_helper,
                                          self.network.namespace)
            ip_wrapper.netns.execute(cmd, addl_env=env)
        else:
            utils.execute(cmd, self.root_helper, addl_env=env)

    def _get_relay_device_name(self):
        return (self.RELAY_DEV_NAME_PREFIX +
                self.network.id)[:self.dev_name_len]

    def _get_relay_ips(self, ip_opt_name):
        # Try to get relay IP from the config.
        relay_ips = getattr(self.conf, ip_opt_name, None)
        # If not specified in config try to get from network object.
        if not relay_ips:
            relay_ips = getattr(self.network, ip_opt_name, None)

        if not relay_ips:
            return None

        try:
            for relay_ip in relay_ips:
                netaddr.IPAddress(relay_ip)
        except netaddr.core.AddrFormatError:
            LOG.error(_('An invalid option value has been provided:'
                        ' %(opt_name)s=%(opt_value)s') %
                      dict(opt_name=ip_opt_name, opt_value=relay_ip))
            return None

        return list(set(relay_ips))


class DnsDhcpProxyDeviceManager(dhcp.DeviceManager):
    def setup_relay(self, network, iface_name, mac_address, relay_bridge):
        if ip_lib.device_exists(iface_name,
                                self.root_helper,
                                network.namespace):
            LOG.debug(_('Reusing existing device: %s.'), iface_name)
        else:
            self.driver.plug(network.id,
                             network.id,
                             iface_name,
                             mac_address,
                             namespace=network.namespace,
                             bridge=relay_bridge)

            use_static_ip_allocation = (
                self.conf.dhcp_relay_management_network
                and hasattr(network, MGMT_INTERFACE_IP_ATTR))

            if use_static_ip_allocation:
                self._allocate_static_ip(network, iface_name)
            else:
                self._allocate_ip_via_dhcp(network, iface_name)

    def destroy_relay(self, network, device_name, relay_bridge):
        self.driver.unplug(device_name, namespace=network.namespace,
                           bridge=relay_bridge)

    def _allocate_static_ip(self, network, iface_name):
        mgmt_net = self.conf.dhcp_relay_management_network
        relay_ip = netaddr.IPAddress(getattr(network, MGMT_INTERFACE_IP_ATTR))
        relay_net = netaddr.IPNetwork(mgmt_net)
        relay_ip_cidr = '/'.join([str(relay_ip), str(relay_net.prefixlen)])
        relay_iface = ip_lib.IPDevice(iface_name, self.root_helper)

        LOG.info(_('Allocating static IP %(relay_ip)s for %(iface_name)s'),
                 {'relay_ip': relay_ip, 'iface_name': iface_name})

        if network.namespace:
            relay_iface.namespace = network.namespace

        relay_iface.addr.add(
            relay_ip.version, relay_ip_cidr, relay_net.broadcast,
            scope='link')

    def _allocate_ip_via_dhcp(self, network, iface_name):
        dhcp_client_cmd = [self.conf.dhclient_path, iface_name]

        LOG.info(_('Running DHCP client for %s interface'), iface_name)

        if network.namespace:
            ip_wrapper = ip_lib.IPWrapper(self.root_helper,
                                          network.namespace)
            ip_wrapper.netns.execute(dhcp_client_cmd)
        else:
            utils.execute(dhcp_client_cmd)
