"""005_nemsis_validation_persistence

Revision ID: 010_nemsis_validation_persistence
Revises: 009_add_nemsis_export_validation_evidence
Create Date: 2026-04-23 12:00:00.000000

Add NEMSIS validation results, errors, and export job tracking tables.
Supports validation persistence, export blocking, and validation history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010_nemsis_validation_persistence'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add NEMSIS validation persistence tables."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")
    
    # Create nemsis_validation_results table
    op.create_table(
        'nemsis_validation_results',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('incident_id', sa.String(36), nullable=False, index=True),
        sa.Column('validation_status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('errors_json', sa.Text, nullable=True),
        sa.Column('warnings_json', sa.Text, nullable=True),
        sa.Column('validation_summary_json', sa.Text, nullable=True),
        sa.Column('error_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('warning_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('created_by_user_id', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.ForeignKeyConstraint(['incident_id'], ['epcr_charts.id'], name='fk_validation_results_incident'),
    )
    
    # Create indexes for validation results
    op.create_index('ix_nemsis_validation_tenant_incident', 'nemsis_validation_results', ['tenant_id', 'incident_id'])
    op.create_index('ix_nemsis_validation_status', 'nemsis_validation_results', ['validation_status'])
    
    # Create nemsis_validation_errors table
    op.create_table(
        'nemsis_validation_errors',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('result_id', sa.String(36), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('element_id', sa.String(128), nullable=True, index=True),
        sa.Column('error_code', sa.String(64), nullable=True, index=True),
        sa.Column('error_message', sa.Text, nullable=False),
        sa.Column('severity', sa.String(32), nullable=False),
        sa.Column('field_path', sa.String(512), nullable=True),
        sa.Column('current_value', sa.Text, nullable=True),
        sa.Column('expected_value', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.ForeignKeyConstraint(['result_id'], ['nemsis_validation_results.id'], name='fk_validation_errors_result', ondelete='CASCADE'),
    )
    
    # Create indexes for validation errors
    op.create_index('ix_nemsis_validation_errors_tenant_element', 'nemsis_validation_errors', ['tenant_id', 'element_id'])
    op.create_index('ix_nemsis_validation_errors_severity', 'nemsis_validation_errors', ['severity'])
    
    # Create nemsis_export_jobs table
    op.create_table(
        'nemsis_export_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.String(36), nullable=False, index=True),
        sa.Column('incident_id', sa.String(36), nullable=False, index=True),
        sa.Column('validation_result_id', sa.String(36), nullable=True, index=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('s3_bucket', sa.String(255), nullable=True),
        sa.Column('s3_key', sa.String(1024), nullable=True),
        sa.Column('file_size_bytes', sa.BigInteger, nullable=True),
        sa.Column('sha256', sa.String(64), nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('retry_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('created_by_user_id', sa.String(255), nullable=False),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.ForeignKeyConstraint(['incident_id'], ['epcr_charts.id'], name='fk_export_jobs_incident'),
        sa.ForeignKeyConstraint(['validation_result_id'], ['nemsis_validation_results.id'], name='fk_export_jobs_validation'),
    )
    
    # Create indexes for export jobs
    op.create_index('ix_nemsis_export_jobs_tenant_incident', 'nemsis_export_jobs', ['tenant_id', 'incident_id'])
    op.create_index('ix_nemsis_export_jobs_status', 'nemsis_export_jobs', ['status'])


def downgrade() -> None:
    """Remove NEMSIS validation persistence tables."""
    
    # Drop indexes
    op.drop_index('ix_nemsis_export_jobs_status', table_name='nemsis_export_jobs')
    op.drop_index('ix_nemsis_export_jobs_tenant_incident', table_name='nemsis_export_jobs')
    op.drop_index('ix_nemsis_validation_errors_severity', table_name='nemsis_validation_errors')
    op.drop_index('ix_nemsis_validation_errors_tenant_element', table_name='nemsis_validation_errors')
    op.drop_index('ix_nemsis_validation_status', table_name='nemsis_validation_results')
    op.drop_index('ix_nemsis_validation_tenant_incident', table_name='nemsis_validation_results')
    
    # Drop tables
    op.drop_table('nemsis_export_jobs')
    op.drop_table('nemsis_validation_errors')
    op.drop_table('nemsis_validation_results')
