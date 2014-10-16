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

import socket

import neutron.ddi.drivers.infoblox.exceptions as ib_exc


def is_valid_ip(ip):
    try:
        socket.inet_aton(ip)
    except socket.error:
        return False

    return True


class Network(object):
    """Sample Infoblox 'network' object in JSON format:
    [
        {
            "_ref": "network/ZG5zLm5ldHdvcmskMTAuMzkuMTEuMC8yNC8w:
                     10.39.11.0/24/default",
            "members": [
                {
                    "_struct": "dhcpmember",
                    "ipv4addr": "10.39.11.123",
                    "name": "infoblox.localdomain"
                }
            ],
            "options": [
                {
                    "name": "dhcp-lease-time",
                    "num": 51,
                    "use_option": false,
                    "value": "43200",
                    "vendor_class": "DHCP"
                },
                {
                    "name": "domain-name-servers",
                    "num": 6,
                    "use_option": true,
                    "value": "10.39.11.123",
                    "vendor_class": "DHCP"
                },
                {
                    "name": "routers",
                    "num": 3,
                    "use_option": false,
                    "value": "10.39.11.1",
                    "vendor_class": "DHCP"
                }
            ]
        }
    ]
    """
    DNS_NAMESERVERS_OPTION = 'domain-name-servers'

    def __init__(self):
        self.infoblox_type = 'network'
        self.members = []
        self.options = []
        self.member_ip_addrs = []
        self.infoblox_reference = None
        self.ref = None

    def __repr__(self):
        return "{}".format(self.to_dict())

    @staticmethod
    def from_dict(network_ib_object):
        net = Network()
        net.members = network_ib_object['members']
        net.options = network_ib_object['options']

        for member in net.members:
            net.member_ip_addrs.append(member['ipv4addr'])
        net.ref = network_ib_object['_ref']
        return net

    @property
    def dns_nameservers(self):
        # NOTE(max_lobur): The behaviour of the WAPI is as follows:
        # * If the subnet created without domain-name-servers option it will
        # be absent in the options list.
        # * If the subnet created with domain-name-servers option and then
        # it's cleared by update operation, the option will be present in
        # the list, will carry the last data, but will have use_option = False
        # Both cases mean that there are NO specified nameservers on NIOS.
        dns_nameservers = []
        for opt in self.options:
            if self._is_dns_option(opt):
                if opt.get('use_option', True):
                    dns_nameservers = opt['value'].split(',')
                    break
        return dns_nameservers

    @dns_nameservers.setter
    def dns_nameservers(self, value):
        for opt in self.options:
            if self._is_dns_option(opt):
                if value:
                    opt['value'] = ",".join(value)
                    opt['use_option'] = True
                else:
                    opt['use_option'] = False
                break
        else:
            if value:
                self.options.append(dict(
                    name=self.DNS_NAMESERVERS_OPTION,
                    value=",".join(value),
                    use_option=True
                ))

    def has_dns_members(self):
        for opt in self.options:
            if self._is_dns_option(opt):
                return True
        return False

    def update_member_ip_in_dns_nameservers(self, relay_ip):
        for opt in self.options:
            if self._is_dns_option(opt):
                opt['value'] = relay_ip
                return

    def to_dict(self):
        return {
            'members': self.members,
            'options': self.options
        }

    @staticmethod
    def _is_dns_option(option):
        return option['name'] == Network.DNS_NAMESERVERS_OPTION


class HostRecordIPv4(object):
    """Sample Infoblox host record object in JSON format:
    {
        "_ref": "record:host/ZG5zLmhvc3QkLjY3OC5jb20uZ2xvYmFsLmNsb3VkLnRl
                 :test_host_name.testsubnet.cloud.global.com/
                 default.687401e9f7a7471abbf301febf99854e",
        "ipv4addrs": [
            {
                "_ref": "record:host_ipv4addr/ZG5zLmhvc3RfYWRkcmVzcyQuNjc4L
                         :192.168.0.5/
                         test_host_name.testsubnet.cloud.global.com/
                         default.687401e9f7a7471abbf301febf99854e",
                "configure_for_dhcp": false,
                "host": "test_host_name.testsubnet.cloud.global.com",
                "ipv4addr": "192.168.0.5",
                "mac": "aa:bb:cc:dd:ee:ff"
            }
        ]
    }
    """
    def __init__(self):
        self.infoblox_type = 'record:host'
        self.hostname = None
        self._zone_auth = None
        self.mac = None
        self.ip = None
        self.dns_view = None

    def __repr__(self):
        return "{}".format(self.to_dict())

    def to_dict(self):
        return {
            'view': self.dns_view,
            'name': '.'.join([self.hostname, self.zone_auth]),
            'ipv4addrs': [{
                    'mac': self.mac,
                    'configure_for_dhcp': True,
                    'ipv4addr': self.ip}
            ]
        }

    return_fields = [
        'ipv4addrs',
    ]

    @staticmethod
    def from_dict(hr_dict):
        ipv4addrs = hr_dict.get('ipv4addrs')
        if not ipv4addrs:
            raise ib_exc.HostRecordNoIPv4Addrs()

        ipv4addr = ipv4addrs[0]
        ip = ipv4addr['ipv4addr']
        if not is_valid_ip(ip):
            raise ib_exc.InfobloxInvalidIp(ip=ip)

        host = ipv4addr.get('host', 'unknown.unknown')
        hostname, _, dns_zone = host.partition('.')
        mac = ipv4addr.get('mac')

        host_record = HostRecordIPv4()
        host_record.hostname = hostname
        host_record.zone_auth = dns_zone
        host_record.mac = mac
        host_record.ip = ip

        return host_record

    @property
    def zone_auth(self):
        return self._zone_auth

    @zone_auth.setter
    def zone_auth(self, value):
        if value:
            self._zone_auth = value.lstrip('.')


class FixedAddress(object):
    def __init__(self):
        self.infoblox_type = 'fixedaddress'
        self.ip = None
        self.net_view = None
        self.mac = None
        self.extattrs = None

    def __repr__(self):
        return "FixedAddress({})".format(self.to_dict())

    return_fields = [
        'ipv4addr',
        'mac',
        'network_view',
        'extattrs'
    ]

    @staticmethod
    def from_dict(fixed_address_dict):
        ip = fixed_address_dict.get('ipv4addr')
        if not is_valid_ip(ip):
            raise ib_exc.InfobloxInvalidIp(ip=ip)

        fa = FixedAddress()
        fa.ip = ip
        fa.mac = fixed_address_dict.get('mac')
        fa.net_view = fixed_address_dict.get('network_view')
        fa.extattrs = fixed_address_dict.get('extattrs')
        return fa

    def to_dict(self):
        return {
            'mac': self.mac,
            'network_view': self.net_view,
            'ipv4addr': self.ip,
            'extattrs': self.extattrs
        }


class Member(object):
    def __init__(self, ip, name):
        self.ip = ip
        self.name = name

    def __eq__(self, other):
        return self.ip == other.ip and self.name == other.name

    def __repr__(self):
        return 'Member(IP={ip}, name={name})'.format(ip=self.ip,
                                                     name=self.name)
