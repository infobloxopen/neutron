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

"""Multiple DHCP members

Revision ID: 256b90dd9824
Revises: 172ace2194db
Create Date: 2014-09-15 05:54:38.612277

"""

# revision identifiers, used by Alembic.
revision = '256b90dd9824'
down_revision = '172ace2194db'

# Change to ['*'] if this migration applies to all plugins

migration_for_plugins = [
    '*'
]

from alembic import op
import sqlalchemy as sa


from neutron.db import migration


def upgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return

    op.create_table(
        'infobloxdhcpmembers',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('network_id', sa.String(length=36), nullable=False),
        sa.Column('server_ip', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['network_id'], ['networks.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))

    op.create_table(
        'infobloxdnsmembers',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('network_id', sa.String(length=36), nullable=False),
        sa.Column('server_ip', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['network_id'], ['networks.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'))

    op.drop_column('networks', 'dhcp_relay_ip')
    op.drop_column('networks', 'dns_relay_ip')


def downgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return

    op.drop_table('infobloxdhcpmembers')
    op.drop_table('infobloxdnsmembers')

    op.add_column(
        'networks',
        sa.Column('dhcp_relay_ip', sa.String(length=64), nullable=True)
    )
    op.add_column(
        'networks',
        sa.Column('dns_relay_ip', sa.String(length=64), nullable=True)
    )
