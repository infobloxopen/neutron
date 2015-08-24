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

"""Infoblox DB v2

Revision ID: 78d27e9172
Revises: 45284803ad19
Create Date: 2014-05-28 11:11:34.815843

"""

# revision identifiers, used by Alembic.
revision = '78d27e9172'
down_revision = 'juno'

# Change to ['*'] if this migration applies to all plugins

migration_for_plugins = ['*']

from alembic import op
import sqlalchemy as sa


def upgrade(active_plugins=None, options=None):
    op.create_table(
        'infoblox_member_maps',
        sa.Column('member_name', sa.String(255), nullable=False),
        sa.Column('map_id', sa.String(255), nullable=True))


def downgrade(active_plugins=None, options=None):
    op.drop_table('infoblox_member_maps')
