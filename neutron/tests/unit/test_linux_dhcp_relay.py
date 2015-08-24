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

import __builtin__
import os

import mock

from neutron.agent.common import config
from neutron.agent.linux import dhcp
from neutron.agent.linux import dhcp_relay
from neutron.agent.linux import interface
from neutron.agent.linux import utils
from neutron.common import config as base_config
from neutron.common import exceptions as exc
from neutron.tests import base


DHCP_RELAY_IP = '192.168.122.32'
DNS_RELAY_IP = '192.168.122.32'


class FakeDeviceManager():
    def __init__(self, conf, root_helper, plugin):
        pass

    def get_interface_name(self, network, port):
        pass

    def get_device_id(self, network):
        pass

    def setup_dhcp_port(self, network):
        pass

    def setup(self, network, reuse_existing=False):
        pass

    def update(self, network):
        pass

    def destroy(self, network, device_name):
        pass

    def setup_relay(self, network, iface_name, mac_address, relay_bridge):
        pass

    def destroy_relay(self, network, device_name, relay_bridge):
        pass


class FakeIPAllocation:
    def __init__(self, address):
        self.ip_address = address


class FakePort1:
    id = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
    admin_state_up = True
    fixed_ips = [FakeIPAllocation('192.168.0.2')]
    mac_address = '00:00:80:aa:bb:cc'

    def __init__(self):
        self.extra_dhcp_opts = []


class FakeV4HostRoute:
    destination = '20.0.0.1/24'
    nexthop = '20.0.0.1'


class FakeV4Subnet:
    id = 'dddddddd-dddd-dddd-dddd-dddddddddddd'
    ip_version = 4
    cidr = '192.168.0.0/24'
    gateway_ip = '192.168.0.1'
    enable_dhcp = True
    host_routes = [FakeV4HostRoute]
    dns_nameservers = ['8.8.8.8']


class FakeV4Network:
    id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    tenant_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    subnets = [FakeV4Subnet()]
    ports = [FakePort1()]
    namespace = 'qdhcp-ns'
    dhcp_relay_ip = DHCP_RELAY_IP
    dns_relay_ip = DNS_RELAY_IP


class FakeOpen():
    def __init__(self, *args):
        pass

    def read(self):
        return 'dhcrelay -a -i tap77777777-77 %s' % DHCP_RELAY_IP


class TestBase(base.BaseTestCase):
    def setUp(self):
        super(TestBase, self).setUp()
        self.network = FakeV4Network()
        root = os.path.dirname(os.path.dirname(__file__))
        args = ['--config-file',
                os.path.join(root, 'etc', 'neutron.conf.test')]
        self.conf = config.setup_conf()
        self.conf.register_opts(base_config.core_opts)
        self.conf.register_opts(dhcp.OPTS)
        self.conf.register_opts(dhcp_relay.OPTS)
        self.conf.register_opts(interface.OPTS)

        def dhcp_dns_proxy_init_mock(self, conf, network, root_helper='sudo',
                                     version=None, plugin=None):
            super(dhcp_relay.DhcpDnsProxy, self).__init__(
                conf, network,
                root_helper,
                version, plugin)

            external_dhcp_servers = self._get_relay_ips(
                'external_dhcp_servers')
            external_dns_servers = self._get_relay_ips('external_dns_servers')
            required_options = {
                'dhcp_relay_bridge': self.conf.dhcp_relay_bridge,
                'external_dhcp_servers': external_dhcp_servers,
                'external_dns_servers': external_dns_servers
            }

            for option_name, option in required_options.iteritems():
                if not option:
                    raise exc.InvalidConfigurationOption(
                        opt_name=option_name,
                        opt_value=option
                    )

            self.dev_name_len = self._calc_dev_name_len()
            self.device_manager = mock.Mock()

        dhcp_dns_proxy_mock = mock.patch(
            "neutron.agent.linux.dhcp_relay.DhcpDnsProxy.__init__",
            dhcp_dns_proxy_init_mock
        )
        dhcp_dns_proxy_mock.start()

        device_manager_init = mock.patch(
            "neutron.agent.linux.dhcp.DeviceManager.__init__",
            lambda *args, **kwargs: None)
        device_manager_init.start()

        self.conf(args=args)
        self.conf.set_override('state_path', '')
        self.conf.dhcp_relay_bridge = 'br-dhcp'

        self.replace_p = mock.patch('neutron.agent.linux.utils.replace_file')
        self.execute_p = mock.patch('neutron.agent.linux.utils.execute')
        self.addCleanup(self.replace_p.stop)
        self.addCleanup(self.execute_p.stop)
        self.safe = self.replace_p.start()
        self.execute = self.execute_p.start()

    def get_fixed_ddi_proxy(self):
        def _get_relay_ips(self, data):
            return ['192.168.122.32']

        attrs_to_mock = {
            '_get_relay_ips': _get_relay_ips
        }

        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock):
            return dhcp_relay.DhcpDnsProxy


class TestDnsDhcpProxy(TestBase):

    def test_create_instance_no_dhcp_relay_server(self):
        self.conf.dhcp_relay_ip = None
        self.network.dhcp_relay_ip = None
        self.assertRaises(exc.InvalidConfigurationOption,
                          dhcp_relay.DhcpDnsProxy,
                          self.conf,
                          self.network)

    def test_create_instance_bad_dhcp_relay_server(self):
        self.conf.dhcp_relay_ip = '192.168.122.322'
        self.assertRaises(exc.InvalidConfigurationOption,
                          dhcp_relay.DhcpDnsProxy,
                          self.conf,
                          self.network)

    def test_create_instance_no_dns_relay_server(self):
        self.conf.dns_relay_ip = None
        self.network.dhcp_relay_ip = None
        self.assertRaises(exc.InvalidConfigurationOption,
                          dhcp_relay.DhcpDnsProxy,
                          self.conf,
                          self.network)

    def test_create_instance_bad_dns_relay_server(self):
        self.conf.dns_relay_ip = '192.168.122.322'
        self.assertRaises(exc.InvalidConfigurationOption,
                          dhcp_relay.DhcpDnsProxy,
                          self.conf,
                          self.network)

    def test_create_instance_no_relay_bridge(self):
        self.conf.dhcp_relay_bridge = None
        self.assertRaises(exc.InvalidConfigurationOption,
                          dhcp_relay.DhcpDnsProxy,
                          self.conf,
                          self.network)

    @mock.patch.object(dhcp_relay.DhcpDnsProxy, "_spawn_dhcp_proxy")
    @mock.patch.object(dhcp_relay.DhcpDnsProxy, "_spawn_dns_proxy")
    def test_spawn(self, mock_spawn_dns, mock_spawn_dhcp):
        attrs_to_mock = {
            '_get_relay_ips': mock.Mock(return_value=['192.168.122.32'])
        }

        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock):
            dm = dhcp_relay.DhcpDnsProxy(self.conf, self.network)
            dm.spawn_process()

            mock_spawn_dns.assert_called_once_with()
            mock_spawn_dhcp.assert_called_once_with()

    @mock.patch.object(dhcp.DhcpLocalProcess, 'get_conf_file_name')
    def test__spawn_dhcp_proxy(self, get_conf_file_name_mock):
        test_dns_conf_path = 'test_dir/dhcp/test_dns_pid'
        get_conf_file_name_mock.return_value = test_dns_conf_path

        expected = [
            'ip',
            'netns',
            'exec',
            'qdhcp-ns',
            'dhcrelay',
            '-4',
            '-a',
            '-pf',
            test_dns_conf_path,
            '-i',
            'tap0',
            '-o',
            'trelaaaaaaaa-a',
            self.network.dhcp_relay_ip
        ]

        self.execute.return_value = ('', '')

        attrs_to_mock = dict(
            [(a, mock.DEFAULT) for a in
            ['interface_name', '_get_relay_ips']]
        )

        attrs_to_mock.update({
            '_get_relay_ips': mock.Mock(return_value=['192.168.122.32'])
        })

        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock) as mocks:
            mocks['interface_name'].__get__ = mock.Mock(return_value='tap0')

            dm = dhcp_relay.DhcpDnsProxy(self.conf, self.network)
            dm._spawn_dhcp_proxy()
            self.execute.assert_called_once_with(expected,
                                                 root_helper='sudo',
                                                 check_exit_code=True)

    @mock.patch.object(dhcp.DhcpLocalProcess, 'get_conf_file_name')
    def test__spawn_dhcp_proxy_no_namespace(self, get_conf_file_name_mock):
        test_dns_conf_path = 'test_dir/dhcp/test_dns_pid'
        get_conf_file_name_mock.return_value = test_dns_conf_path
        self.network.namespace = None

        expected = [
            'dhcrelay',
            '-4',
            '-a',
            '-pf',
            test_dns_conf_path,
            '-i',
            'tap0',
            '-o',
            'trelaaaaaaaa-a',
            self.network.dhcp_relay_ip
        ]

        self.execute.return_value = ('', '')

        attrs_to_mock = dict(
            [(a, mock.DEFAULT) for a in
            ['interface_name', '_get_relay_ips']]
        )

        attrs_to_mock.update({
            '_get_relay_ips': mock.Mock(return_value=['192.168.122.32'])
        })

        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock) as mocks:
            mocks['interface_name'].__get__ = mock.Mock(return_value='tap0')

            dm = dhcp_relay.DhcpDnsProxy(self.conf, self.network)
            dm._spawn_dhcp_proxy()
            self.execute.assert_called_once_with(expected, 'sudo')

    @mock.patch.object(dhcp_relay.DhcpDnsProxy, 'interface_name')
    @mock.patch.object(dhcp.DhcpLocalProcess, 'get_conf_file_name')
    def test__spawn_dns_proxy(self, get_conf_file_name_mock, iface_name_mock):
        test_dns_conf_path = 'test_dir/dhcp/test_dns_pid'
        get_conf_file_name_mock.return_value = test_dns_conf_path
        iface_name_mock.__get__ = mock.Mock(return_value='test_tap0')
        expected = [
            'ip',
            'netns',
            'exec',
            'qdhcp-ns',
            'dnsmasq',
            '--no-hosts',
            '--no-resolv',
            '--strict-order',
            '--bind-interfaces',
            '--interface=test_tap0',
            '--except-interface=lo',
            '--all-servers',
            '--server=%s' % self.network.dns_relay_ip,
            '--pid-file=%s' % test_dns_conf_path
        ]
        self.execute.return_value = ('', '')

        attrs_to_mock = {
            '_get_relay_ips': mock.Mock(return_value=['192.168.122.32'])
        }

        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock):

            dm = dhcp_relay.DhcpDnsProxy(self.conf, self.network)
            dm._spawn_dns_proxy()

            self.execute.assert_called_once_with(expected,
                                                 root_helper='sudo',
                                                 check_exit_code=True)

    @mock.patch.object(dhcp_relay.DhcpDnsProxy, 'interface_name')
    @mock.patch.object(dhcp.DhcpLocalProcess, 'get_conf_file_name')
    def test__spawn_dns_proxy_no_namespace(self, get_conf_file_name_mock,
                                           iface_name_mock):
        self.network.namespace = None
        test_dns_conf_path = 'test_dir/dhcp/test_dns_pid'
        get_conf_file_name_mock.return_value = test_dns_conf_path
        iface_name_mock.__get__ = mock.Mock(return_value='test_tap0')
        expected = [
            'dnsmasq',
            '--no-hosts',
            '--no-resolv',
            '--strict-order',
            '--bind-interfaces',
            '--interface=test_tap0',
            '--except-interface=lo',
            '--all-servers',
            '--server=%s' % self.network.dns_relay_ip,
            '--pid-file=%s' % test_dns_conf_path
        ]
        self.execute.return_value = ('', '')

        attrs_to_mock = {
            '_get_relay_ips': mock.Mock(return_value=['192.168.122.32'])}

        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock):
            dm = dhcp_relay.DhcpDnsProxy(self.conf, self.network)
            dm._spawn_dns_proxy()

            self.execute.assert_called_once_with(expected, 'sudo')

    @mock.patch.object(dhcp_relay, '_generate_mac_address',
                       mock.Mock(return_value='77:77:77:77:77:77'))
    @mock.patch.object(dhcp_relay.DhcpDnsProxy, '_get_relay_device_name',
                       mock.Mock(return_value='tap-relay77777'))
    @mock.patch.object(FakeDeviceManager, 'setup',
                       mock.Mock(return_value='tap-77777777'))
    @mock.patch.object(FakeDeviceManager, 'setup_relay', mock.Mock())
    def test_enable_dhcp_dns_inactive(self):
        attrs_to_mock = dict(
            [(a, mock.DEFAULT) for a in
             ['interface_name', '_get_relay_ips', 'restart',
              'is_dhcp_active', 'is_dns_active', 'spawn_process']]
        )

        attrs_to_mock.update(
            {'_get_relay_ips': mock.Mock(return_value=['192.168.122.32']),
             'is_dhcp_active': mock.Mock(return_value=True),
             'is_dns_active': mock.Mock(return_value=True),
             'spawn_process': mock.Mock(return_value=None)}
        )
        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock) as mocks:
            mocks['interface_name'].__set__ = mock.Mock()

            dr = dhcp_relay.DhcpDnsProxy(self.conf, self.network)
            dr.enable()

            dr.device_manager.setup_relay.assert_called_once_with(
                self.network,
                'tap-relay77777',
                '77:77:77:77:77:77',
                self.conf.dhcp_relay_bridge)
            dr.device_manager.setup.assert_called_once_with(
                self.network,
                reuse_existing=True)

    @mock.patch.object(dhcp_relay, '_generate_mac_address',
                       mock.Mock(return_value='77:77:77:77:77:77'))
    @mock.patch.object(dhcp_relay.DhcpDnsProxy, '_get_relay_device_name',
                       mock.Mock(return_value='tap-relay77777'))
    @mock.patch.object(FakeDeviceManager, 'setup',
                       mock.Mock(return_value='tap-77777777'))
    @mock.patch.object(FakeDeviceManager, 'setup_relay', mock.Mock())
    def test_enable_dhcp_dns_active(self):
        attrs_to_mock = dict(
            [(a, mock.DEFAULT) for a in
            ['interface_name', 'is_dhcp_active', 'is_dns_active', 'restart',
             '_get_relay_ips']]
        )

        attrs_to_mock.update(
            {'_get_relay_ips': mock.Mock(return_value=['192.168.122.32']),
             'is_dhcp_active': mock.Mock(return_value=True),
             'is_dns_active': mock.Mock(return_value=True)}
        )

        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock) as mocks:
            mocks['interface_name'].__set__ = mock.Mock()

            dr = dhcp_relay.DhcpDnsProxy(self.conf, self.network)
            dr.enable()

            dr.device_manager.setup_relay.assert_called_once_with(
                self.network,
                'tap-relay77777',
                '77:77:77:77:77:77',
                self.conf.dhcp_relay_bridge)
            dr.device_manager.setup.assert_called_once_with(
                self.network,
                reuse_existing=True)
            mocks['restart'].assert_any_call()

    def test_disable_retain_port(self):
        attrs_to_mock = dict(
            [(a, mock.DEFAULT) for a in
            ['is_dhcp_active', 'is_dns_active', 'get_dhcp_pid', 'get_dns_pid',
             'restart', '_remove_config_files']]
        )

        attrs_to_mock.update(
            {'_get_relay_ips': mock.Mock(return_value=['192.168.122.32']),
             'is_dhcp_active': mock.Mock(return_value=True),
             'is_dns_active': mock.Mock(return_value=True),
             'get_dhcp_pid': mock.Mock(return_value='1111'),
             'get_dns_pid': mock.Mock(return_value='2222')}
        )

        kill_proc_calls = [
            mock.call(['kill', '-9', '1111'], 'sudo'),
            mock.call(['kill', '-9', '2222'], 'sudo')]

        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock) as mocks:
            dr = dhcp_relay.DhcpDnsProxy(self.conf, self.network)
            dr.disable(retain_port=True)

            self.execute.assert_has_calls(kill_proc_calls)
            mocks['_remove_config_files'].assert_any_call()

    @mock.patch.object(dhcp_relay.DhcpDnsProxy, '_get_relay_device_name',
                       mock.Mock(return_value='tap-relay77777'))
    @mock.patch.object(FakeDeviceManager, 'destroy', mock.Mock())
    @mock.patch.object(FakeDeviceManager, 'destroy_relay', mock.Mock())
    def test_disable_no_retain_port(self):
        attrs_to_mock = dict(
            [(a, mock.DEFAULT) for a in
            ['is_dhcp_active', 'is_dns_active', 'get_dhcp_pid',
             'get_dhcp_pid', 'interface_name', '_remove_config_files']]
        )

        attrs_to_mock.update(
            {'_get_relay_ips': mock.Mock(return_value=['192.168.122.32']),
             'is_dhcp_active': mock.Mock(return_value=True),
             'is_dns_active': mock.Mock(return_value=True),
             'get_dhcp_pid': mock.Mock(return_value='1111'),
             'get_dns_pid': mock.Mock(return_value='2222')}
        )

        kill_proc_calls = [
            mock.call(['kill', '-9', '1111'], 'sudo'),
            mock.call(['kill', '-9', '2222'], 'sudo')]

        with mock.patch.multiple(dhcp_relay.DhcpDnsProxy,
                                 **attrs_to_mock) as mocks:
            mocks['interface_name'].__get__ = mock.Mock(
                return_value='tap-77777777')

            dr = dhcp_relay.DhcpDnsProxy(self.conf, self.network)
            dr.disable(retain_port=False)

            self.execute.assert_has_calls(kill_proc_calls)
            dr.device_manager.destroy.assert_called_once_with(self.network,
                                                              'tap-77777777')
            dr.device_manager.destroy_relay.assert_called_once_with(
                self.network,
                'tap-relay77777',
                self.conf.dhcp_relay_bridge)

            mocks['_remove_config_files'].assert_any_call()

    def test_generate_mac(self):
        mac = dhcp_relay._generate_mac_address()
        mac_array = mac.split(':')
        self.assertEqual(6, len(mac_array))
        for item in mac_array:
            self.assertEqual(2, len(item))
