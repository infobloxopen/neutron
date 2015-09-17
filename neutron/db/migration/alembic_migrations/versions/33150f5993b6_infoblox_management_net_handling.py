# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2014 OpenStack Foundation
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
#

"""Infoblox management net handling

Currently DHCP relay is using dynamic DHCP to get the management IP address.
This is not desirable from customer point of view as they do want a static IP
assignment for such cases which will reduce any potential issue.

Revision ID: 33150f5993b6
Revises: 256b90dd9824
Create Date: 2014-08-28 14:40:20.585390

"""

# revision identifiers, used by Alembic.
revision = '33150f5993b6'
down_revision = '256b90dd9824'

# Change to ['*'] if this migration applies to all plugins

migration_for_plugins = [
    '*'
]

from alembic import op
import sqlalchemy as sa


def upgrade(active_plugins=None, options=None):
    op.create_table('infoblox_mgmt_net_ips',
                    sa.Column('network_id',
                              sa.String(length=255),
                              primary_key=True),
                    sa.Column('ip_address',
                              sa.String(length=64),
                              nullable=False),
                    sa.Column('fixed_address_ref',
                              sa.String(length=255),
                              nullable=False))


def downgrade(active_plugins=None, options=None):
    op.drop_table('infoblox_mgmt_net_ips')
