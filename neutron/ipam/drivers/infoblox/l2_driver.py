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
import re
import six

from oslo.config import cfg

from oslo_utils import importutils
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class L2DriverBase(object):
    """Defines interface for retreiving info from L2 pluings.
    L2 Driver should:
       - be located under 'l2_drivers' directory;
       - have name {core_plugin_name}.py;
       - have class name 'Driver';
       - be inherited from this class;
       - implement methods which are marked as abstractmethods;
    """
    @abc.abstractmethod
    def init_driver(self):
        """Should be implemented in driver for L2 plugin.
        This method should import needed L2 plugin and
        store reference to it somewhere in self.
        So any import exception should be raised at this point.
        """
        pass

    @abc.abstractmethod
    def get_network_binding(self, session, network_id):
        """Should be implemented in driver for L2 plugin.
        :param session: database session object
        :param network_id: network id
         """
        pass

    def __init__(self):
        """No need to override this in child.
        Just inits L2 modules for now.
        """
        self.init_driver()


class L2Info(object):
    """This class provides network info from L2 plugins
    using factory of facades.
    """
    def __init__(self, core_plugin=None):
        """
        :param: core_plugin: OpenStack core plugin
        will be loaded from config if not provided
        """
        if not core_plugin:
            core_plugin = cfg.CONF.core_plugin
        self.core_plugin = core_plugin
        self.driver = None

    def _get_driver(self):
        """Return Driver for L2 plugin.
        Loads appropriate module if not loaded yet.
        """
        if not self.driver:
            self.driver = L2DriverFactory.load(self.core_plugin)
        return self.driver

    def get_network_l2_info(self, session, network_id):
        """Decorator/wrapper method for get_network_binding()
        Converts network info from L2Driver(list format) into
        dict with fixed keys.
        :param session: database session object
        :param network_id: network id
        """
        segments = None
        l2_info = {'network_type': None,
                   'segmentation_id': None,
                   'physical_network': None}

        driver = self._get_driver()
        segments = driver.get_network_binding(session, network_id)

        if segments:
            for name, value in segments.iteritems():
                l2_info[name] = value

        return l2_info


class L2DriverFactory(object):
    """This class loads Driver for L2 plugin
    depending on L2 core_plugin class name.
    """

    @classmethod
    def load(cls, core_plugin):
        """Loads driver for core_plugin
        """
        driver_prefix = 'neutron.ipam.drivers.infoblox.l2_drivers.'
        driver_postfix = '.Driver'
        # Look for infoblox driver for core plugin
        plugin_name = cls.get_plugin_name(core_plugin)
        driver = driver_prefix + plugin_name + driver_postfix
        LOG.info(_("Loading driver %s for core plugin"), driver)
        # Try to load driver, generates exception if fails
        driver_class = importutils.import_class(driver)
        return driver_class()

    @classmethod
    def get_plugin_name(cls, core_plugin):
        """Returns plugin name based on plugin path.
        Plugin name can be found on position number three in path
        neutron.plugins.{plugin_name}.(path_to_module)
        """
        plugin = str(core_plugin)
        match = re.match(r'^neutron\.plugins\.([a-zA-Z0-9_]+)\.',
                         plugin)
        if match:
            return match.group(1)

        # if plugin doesn't match, assume core_plugin is short name
        # instead of full path to module.
        # See examples of full path / short name in setup.cfg
        return plugin
