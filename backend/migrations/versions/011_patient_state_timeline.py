"""011_patient_state_timeline

Revision ID: 011_patient_state_timeline
Revises: 010_nemsis_validation_persistence
Create Date: 2026-04-23 12:00:00.000000

Add patient state timeline table for immutable state progression tracking.
Append-only audit log of all patient care state transitions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011_patient_state_timeline'
down_revision: Union[str, None] = '010_nemsis_validation_persistence'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add patient state timeline table."""
    
    # Create patient_state_timeline table
    op.create_table(
        'patient_state_timeline',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('incident_id', sa.String(36), nullable=False, index=True),
        sa.Column('patient_id', sa.String(36), nullable=True, index=True),
        sa.Column('state_name', sa.String(128), nullable=False, index=True),
        sa.Column('prior_state', sa.String(128), nullable=True),
        sa.Column('changed_by', sa.String(255), nullable=True),
        sa.Column('entity_type', sa.String(64), nullable=True),
        sa.Column('entity_id', sa.String(36), nullable=True),
        sa.Column('metadata_json', sa.Text, nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['incident_id'], ['epcr_charts.id'], name='fk_timeline_incident'),
    )
    
    # Create indexes for timeline queries
    op.create_index('ix_timeline_tenant_incident', 'patient_state_timeline', ['tenant_id', 'incident_id'])
    op.create_index('ix_timeline_tenant_patient', 'patient_state_timeline', ['tenant_id', 'patient_id'])
    op.create_index('ix_timeline_state_name', 'patient_state_timeline', ['state_name'])
    op.create_index('ix_timeline_entity', 'patient_state_timeline', ['entity_type', 'entity_id'])
    op.create_index('ix_timeline_changed_at', 'patient_state_timeline', ['changed_at'])


def downgrade() -> None:
    """Remove patient state timeline table."""
    
    # Drop indexes
    op.drop_index('ix_timeline_changed_at', table_name='patient_state_timeline')
    op.drop_index('ix_timeline_entity', table_name='patient_state_timeline')
    op.drop_index('ix_timeline_state_name', table_name='patient_state_timeline')
    op.drop_index('ix_timeline_tenant_patient', table_name='patient_state_timeline')
    op.drop_index('ix_timeline_tenant_incident', table_name='patient_state_timeline')
    
    # Drop table
    op.drop_table('patient_state_timeline')
