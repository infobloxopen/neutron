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

from oslo.config import cfg
from sqlalchemy.orm import exc

import functools
import time

from oslo.config import cfg
from neutron.db import external_net_db
from neutron.db.infoblox import models
from neutron.db import l3_db
from neutron.db import models_v2
from neutron.openstack.common import log as logging
#from neutron.openstack.common.db import exception as db_exc
from oslo.db import exception as db_exc


OPTS = [
    cfg.IntOpt('infoblox_db_retry_interval',
               default=5,
               help=_('Seconds between db connection retries')),
    cfg.IntOpt('infoblox_db_max_try',
               default=20,
               help=_('Maximum retries before error is raised. '
                      '(setting -1 implies an infinite retry count)')),
    cfg.BoolOpt('infoblox_db_inc_retry_interval',
                default=True,
                help=_('Whether to increase interval between retries, '
                       'up to infoblox_db_max_retry_interval')),
    cfg.IntOpt('infoblox_db_max_retry_interval',
               default=600,
               help='Max seconds for total retries, if '
                    'infoblox_db_inc_retry_interval is enabled')
]

cfg.CONF.register_opts(OPTS)

LOG = logging.getLogger(__name__)


def _retry_db_error(func):
    @functools.wraps(func)
    def callee(*args, **kwargs):
        next_interval = cfg.CONF.infoblox_db_retry_interval
        remaining = cfg.CONF.infoblox_db_max_try
        while True:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                LOG.warn(_("DB error on %s: %s"
                           % (func, str(e))))
                if remaining == 0:
                    LOG.exception(_('DB exceeded retry limit.'))
                    raise db_exc.DBError(e)
                if remaining != -1:
                    remaining -= 1
                time.sleep(next_interval)
                if cfg.CONF.infoblox_db_inc_retry_interval:
                    next_interval = min(
                        next_interval * 2,
                        cfg.CONF.infoblox_db_max_retry_interval
                    )
    return callee


def get_used_members(context, member_type):
    """Returns used members where map_id is not null."""
    q = context.session.query(models.InfobloxMemberMap)
    members = q.filter(models.InfobloxMemberMap.member_type ==
                       member_type).\
        filter(models.InfobloxMemberMap.map_id.isnot(None)).\
        distinct()
    return members


def get_registered_members(context, member_type):
    """Returns registered members."""
    q = context.session.query(models.InfobloxMemberMap)
    members = q.filter_by(member_type=member_type).distinct()
    return members


@_retry_db_error
def get_available_member(context, member_type):
    """Returns available members."""
    q = context.session.query(models.InfobloxMemberMap)
    q = q.filter(models.InfobloxMemberMap.member_type == member_type)
    member = q.filter(models.InfobloxMemberMap.map_id.is_(None)).\
        with_lockmode("update").\
        first()
    return member


def get_members(context, map_id, member_type):
    """Returns members used by currently used mapping (tenant id,
    network id or Infoblox netview name).
    """
    q = context.session.query(models.InfobloxMemberMap)
    members = q.filter_by(map_id=map_id, member_type=member_type).all()
    return members


def register_member(context, map_id, member_name, member_type):
    if map_id:
        context.session.add(
            models.InfobloxMemberMap(map_id=map_id,
                                     member_name=member_name,
                                     member_type=member_type))
    else:
        context.session.add(
            models.InfobloxMemberMap(member_name=member_name,
                                     member_type=member_type))


def attach_member(context, map_id, member_name, member_type):
    context.session.query(models.InfobloxMemberMap.member_name).\
        filter_by(member_name=member_name, member_type=member_type).\
        update({'map_id': map_id})


def delete_members(context, map_id):
    with context.session.begin(subtransactions=True):
        context.session.query(
            models.InfobloxMemberMap).filter_by(map_id=map_id).delete()


@_retry_db_error
def release_member(context, map_id):
    context.session.query(models.InfobloxMemberMap.member_name).\
        filter_by(map_id=map_id).update({'map_id': None})


def is_last_subnet(context, subnet_id):
    q = context.session.query(models_v2.Subnet)
    return q.filter(models_v2.Subnet.id != subnet_id).count() == 0


def is_last_subnet_in_network(context, subnet_id, network_id):
    q = context.session.query(models_v2.Subnet)
    return q.filter(models_v2.Subnet.id != subnet_id,
                    models_v2.Subnet.network_id == network_id).count() == 0


def is_last_subnet_in_tenant(context, subnet_id, tenant_id):
    q = context.session.query(models_v2.Subnet)
    return q.filter(models_v2.Subnet.id != subnet_id,
                    models_v2.Subnet.tenant_id == tenant_id).count() == 0


def is_last_subnet_in_private_networks(context, subnet_id):
    sub_qry = context.session.query(
        external_net_db.ExternalNetwork.network_id)
    q = context.session.query(models_v2.Subnet.id)
    q = q.filter(models_v2.Subnet.id != subnet_id)
    q = q.filter(~models_v2.Subnet.network_id.in_(sub_qry))
    return q.count() == 0


def is_network_external(context, network_id):
    q = context.session.query(external_net_db.ExternalNetwork)
    return q.filter_by(network_id=network_id).count() > 0


def delete_ip_allocation(context, network_id, subnet, ip_address):
    # Delete the IP address from the IPAllocate table
    subnet_id = subnet['id']
    LOG.debug(_("Delete allocated IP %(ip_address)s "
                "(%(network_id)s/%(subnet_id)s)"), locals())
    alloc_qry = context.session.query(
        models_v2.IPAllocation).with_lockmode('update')
    alloc_qry.filter_by(network_id=network_id,
                        ip_address=ip_address,
                        subnet_id=subnet_id).delete()


def get_subnets_by_network(context, network_id):
    subnet_qry = context.session.query(models_v2.Subnet)
    return subnet_qry.filter_by(network_id=network_id).all()


def get_subnets_by_port(context, port_id):
    allocs = (context.session.query(models_v2.IPAllocation).
              join(models_v2.Port).
              filter_by(id=port_id)
              .all())
    subnets = []
    subnet_qry = context.session.query(models_v2.Subnet)
    for allocation in allocs:
        subnets.append(subnet_qry.
                       filter_by(id=allocation.subnet_id).
                       first())
    return subnets


def get_port_by_id(context, port_id):
    query = context.session.query(models_v2.Port)
    return query.filter_by(id=port_id).one()


def get_network_name(context, subnet):
    q = context.session.query(models_v2.Network)
    net_name = q.join(models_v2.Subnet).filter(
        models_v2.Subnet.id == subnet['id']).first()
    if net_name:
        return net_name.name
    return None


def get_instance_id_by_floating_ip(context, floating_ip_id):
    query = context.session.query(l3_db.FloatingIP, models_v2.Port)
    query = query.filter(l3_db.FloatingIP.id == floating_ip_id)
    query = query.filter(models_v2.Port.id == l3_db.FloatingIP.fixed_port_id)
    result = query.first()
    if result:
        return result.Port.device_id
    return None


def get_subnet_dhcp_port_address(context, subnet_id):
    dhcp_port = (context.session.query(models_v2.IPAllocation).
                 filter_by(subnet_id=subnet_id).
                 join(models_v2.Port).
                 filter_by(device_owner='network:dhcp')
                 .first())
    if dhcp_port:
        return dhcp_port.ip_address
    return None


def get_network_view(context, network_id):
    query = context.session.query(models.InfobloxNetViews)
    net_view = query.filter_by(network_id=network_id).first()
    if net_view:
        return net_view.network_view
    return None


def set_network_view(context, network_view, network_id):
    ib_net_view = models.InfobloxNetViews(network_id=network_id,
                                          network_view=network_view)

    # there should be only one NIOS network view per Openstack network
    query = context.session.query(models.InfobloxNetViews)
    obj = query.filter_by(network_id=network_id).first()
    if not obj:
        context.session.add(ib_net_view)


def add_management_ip(context, network_id, fixed_address):
    context.session.add(models.InfobloxManagementNetIps(
        network_id=network_id,
        ip_address=fixed_address.ip,
        fixed_address_ref=fixed_address.ref))


def delete_management_ip(context, network_id):
    query = context.session.query(models.InfobloxManagementNetIps)
    query.filter_by(network_id=network_id).delete()


def get_management_ip_ref(context, network_id):
    query = context.session.query(models.InfobloxManagementNetIps)
    mgmt_ip = query.filter_by(network_id=network_id).first()
    return mgmt_ip.fixed_address_ref if mgmt_ip else None


def get_management_net_ip(context, network_id):
    query = context.session.query(models.InfobloxManagementNetIps)
    mgmt_ip = query.filter_by(network_id=network_id).first()
    return mgmt_ip.ip_address if mgmt_ip else None


def get_network(context, network_id):
    network_qry = context.session.query(models_v2.Network)
    return network_qry.filter_by(id=network_id).one()


def get_subnet(context, subnet_id):
    subnet_qry = context.session.query(models_v2.Subnet)
    return subnet_qry.filter_by(id=subnet_id).one()
