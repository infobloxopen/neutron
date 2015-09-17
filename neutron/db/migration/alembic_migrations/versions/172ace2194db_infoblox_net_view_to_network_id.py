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

"""Infoblox net view to network ID

Revision ID: 172ace2194db
Revises: d9841b33bd
Create Date: 2014-09-09 11:03:23.737412

"""

# revision identifiers, used by Alembic.
revision = '172ace2194db'
down_revision = 'd9841b33bd'

# Change to ['*'] if this migration applies to all plugins

migration_for_plugins = ['*']

from alembic import op
import sqlalchemy as sa


def upgrade(active_plugins=None, options=None):
    op.create_table('infoblox_net_views',
                    sa.Column('network_id',
                              sa.String(36),
                              sa.ForeignKey("networks.id",
                                            ondelete="CASCADE"),
                              nullable=False,
                              primary_key=True),
                    sa.Column('network_view', sa.String(56)))


def downgrade(active_plugins=None, options=None):
    op.drop_table('infoblox_net_views')
