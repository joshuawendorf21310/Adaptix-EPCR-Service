"""Initial epcr (ePCR) schema with NEMSIS 3.5.1 compliance

Revision ID: 001
Revises:
Create Date: 2026-04-11

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'epcr_charts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('call_number', sa.String(50), nullable=False, unique=True, index=True),
        sa.Column('patient_id', sa.String(36), nullable=True),
        sa.Column('incident_type', sa.String(50), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('created_by_user_id', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
        if_not_exists=True)
    
    op.create_table(
        'epcr_vitals',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('chart_id', sa.String(36), sa.ForeignKey('epcr_charts.id'), nullable=False),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('bp_sys', sa.Integer(), nullable=True),
        sa.Column('bp_dia', sa.Integer(), nullable=True),
        sa.Column('hr', sa.Integer(), nullable=True),
        sa.Column('rr', sa.Integer(), nullable=True),
        sa.Column('temp_f', sa.Float(), nullable=True),
        sa.Column('spo2', sa.Integer(), nullable=True),
        sa.Column('glucose', sa.Integer(), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)
    
    op.create_table(
        'epcr_assessments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('chart_id', sa.String(36), sa.ForeignKey('epcr_charts.id'), nullable=False, unique=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('chief_complaint', sa.String(500), nullable=True),
        sa.Column('field_diagnosis', sa.String(500), nullable=True),
        sa.Column('documented_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True)
    
    op.create_table(
        'epcr_nemsis_mappings',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('chart_id', sa.String(36), sa.ForeignKey('epcr_charts.id'), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('nemsis_field', sa.String(255), nullable=False, index=True),
        sa.Column('nemsis_value', sa.Text(), nullable=True),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)
    
    op.create_table(
        'epcr_nemsis_compliance',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('chart_id', sa.String(36), sa.ForeignKey('epcr_charts.id'), nullable=False, unique=True, index=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('compliance_status', sa.String(50), nullable=False),
        sa.Column('mandatory_fields_filled', sa.Integer(), nullable=False),
        sa.Column('mandatory_fields_required', sa.Integer(), nullable=False),
        sa.Column('missing_mandatory_fields', sa.Text(), nullable=True),
        sa.Column('compliance_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True)

def downgrade() -> None:
    op.drop_table('epcr_nemsis_compliance')
    op.drop_table('epcr_nemsis_mappings')
    op.drop_table('epcr_assessments')
    op.drop_table('epcr_vitals')
    op.drop_table('epcr_charts')
