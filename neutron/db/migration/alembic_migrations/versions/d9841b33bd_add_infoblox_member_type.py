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

"""Add Infoblox member type

Revision ID: d9841b33bd
Revises: 78d27e9172
Create Date: 2014-06-23 18:25:15.557835

"""

# revision identifiers, used by Alembic.
revision = 'd9841b33bd'
down_revision = '78d27e9172'

# Change to ['*'] if this migration applies to all plugins

migration_for_plugins = ['*']

from alembic import op
import sqlalchemy as sa


def upgrade(active_plugins=None, options=None):
    op.add_column('infoblox_member_maps',
                  sa.Column('member_type', sa.String(10)))
    op.execute("UPDATE infoblox_member_maps SET member_type='dhcp'")


def downgrade(active_plugins=None, options=None):
    op.drop_column('infoblox_member_maps', 'member_type')
