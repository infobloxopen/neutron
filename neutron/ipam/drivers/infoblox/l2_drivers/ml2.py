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

from neutron.ipam.drivers.infoblox import l2_driver


class Driver(l2_driver.L2DriverBase):
    def init_driver(self):
        from neutron.plugins.ml2 import db
        self.db = db

    def get_network_binding(self, session, network_id):
        # get_network_segments returns array of arrays,
        # and we need only the first array
        return self.db.get_network_segments(session, network_id)[0]
