# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2014 OpenStack LLC.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
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

import mock

from neutron.common import exceptions as q_exc
from neutron.ipam.drivers import neutron_ipam
from neutron.tests import base


class SubnetCreateTestCase(base.BaseTestCase):
    def test_subnet_is_created(self):
        dns_controller = mock.Mock()
        dhcp_controller = mock.Mock()
        ipam_controller = mock.MagicMock()
        db_manager = mock.Mock()
        context = mock.MagicMock()
        subnet = mock.Mock()

        ipam_driver = neutron_ipam.NeutronIPAM(
            dhcp_controller=dhcp_controller,
            dns_controller=dns_controller,
            ipam_controller=ipam_controller,
            db_mgr=db_manager)

        ipam_driver.create_subnet(context, subnet)

        assert ipam_controller.create_subnet.called_once

    def test_dhcp_is_configured(self):
        dns_controller = mock.Mock()
        dhcp_controller = mock.Mock()
        ipam_controller = mock.MagicMock()
        db_manager = mock.Mock()
        context = mock.MagicMock()
        subnet = mock.Mock()

        ipam_driver = neutron_ipam.NeutronIPAM(
            dhcp_controller=dhcp_controller,
            dns_controller=dns_controller,
            ipam_controller=ipam_controller,
            db_mgr=db_manager)

        ipam_driver.create_subnet(context, subnet)

        assert dhcp_controller.configure_dhcp.called_once


class SubnetDeleteTestCase(base.BaseTestCase):
    def test_dns_zones_are_deleted(self):
        dns_controller = mock.Mock()
        dhcp_controller = mock.Mock()
        ipam_controller = mock.Mock()
        db_manager = mock.Mock()
        context = mock.MagicMock()
        subnet_id = mock.Mock()

        ipam_driver = neutron_ipam.NeutronIPAM(
            dhcp_controller=dhcp_controller,
            dns_controller=dns_controller,
            ipam_controller=ipam_controller,
            db_mgr=db_manager)

        db_manager.subnet_has_ports_allocated.return_value = False
        db_manager.get_subnet_ports.return_value = []
        ipam_driver.delete_subnet(context, subnet_id)

        assert dns_controller.delete_dns_zones.called_once

    def test_dhcp_gets_disabled(self):
        dns_controller = mock.Mock()
        dhcp_controller = mock.Mock()
        ipam_controller = mock.Mock()
        db_manager = mock.Mock()
        context = mock.MagicMock()
        subnet_id = mock.Mock()

        ipam_driver = neutron_ipam.NeutronIPAM(
            dhcp_controller=dhcp_controller,
            dns_controller=dns_controller,
            ipam_controller=ipam_controller,
            db_mgr=db_manager)

        db_manager.subnet_has_ports_allocated.return_value = False
        db_manager.get_subnet_ports.return_value = []
        ipam_driver.delete_subnet(context, subnet_id)

        assert dhcp_controller.disable_dhcp.called_once

    def test_subnet_is_deleted_from_ipam(self):
        dns_controller = mock.Mock()
        dhcp_controller = mock.Mock()
        ipam_controller = mock.Mock()
        db_manager = mock.Mock()
        context = mock.MagicMock()
        subnet_id = mock.Mock()

        ipam_driver = neutron_ipam.NeutronIPAM(
            dhcp_controller=dhcp_controller,
            dns_controller=dns_controller,
            ipam_controller=ipam_controller,
            db_mgr=db_manager)

        db_manager.subnet_has_ports_allocated.return_value = False
        db_manager.get_subnet_ports.return_value = []
        ipam_driver.delete_subnet(context, subnet_id)

        assert ipam_controller.delete_subnet.called_once

    def test_raises_error_if_subnet_has_active_ports(self):
        dns_controller = mock.Mock()
        dhcp_controller = mock.Mock()
        ipam_controller = mock.MagicMock()
        db_manager = mock.Mock()
        context = mock.MagicMock()
        subnet_id = mock.Mock()

        ipam_driver = neutron_ipam.NeutronIPAM(
            dhcp_controller=dhcp_controller,
            dns_controller=dns_controller,
            ipam_controller=ipam_controller,
            db_mgr=db_manager)

        db_manager.subnet_has_ports_allocated.return_value = True
        db_manager.get_subnet_ports.return_value = [mock.MagicMock()]
        self.assertRaises(q_exc.SubnetInUse, ipam_driver.delete_subnet,
                          context, subnet_id)


class AllocateIPTestCase(base.BaseTestCase):
    def test_allocates_ip(self):
        dns_controller = mock.Mock()
        dhcp_controller = mock.Mock()
        ipam_controller = mock.Mock()
        db_manager = mock.Mock()
        context = mock.MagicMock()
        host = mock.MagicMock()
        ip = mock.Mock()

        ipam_driver = neutron_ipam.NeutronIPAM(
            dhcp_controller=dhcp_controller,
            dns_controller=dns_controller,
            ipam_controller=ipam_controller,
            db_mgr=db_manager)

        ipam_driver.allocate_ip(context, host, ip)

        assert ipam_controller.allocate_ip.called_once

    def test_binds_mac(self):
        dns_controller = mock.Mock()
        dhcp_controller = mock.Mock()
        ipam_controller = mock.Mock()
        db_manager = mock.Mock()
        context = mock.MagicMock()
        host = mock.MagicMock()
        ip = mock.Mock()

        ipam_driver = neutron_ipam.NeutronIPAM(
            dhcp_controller=dhcp_controller,
            dns_controller=dns_controller,
            ipam_controller=ipam_controller,
            db_mgr=db_manager)

        ipam_driver.allocate_ip(context, host, ip)

        assert dhcp_controller.bind_mac.called_once
