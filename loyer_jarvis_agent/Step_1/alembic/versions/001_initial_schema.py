"""Initial schema with pgvector support

Revision ID: 001
Revises:
Create Date: 2026-06-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('google_calendar_token', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    op.create_table('cases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_number', sa.String(255), nullable=False),
        sa.Column('court', sa.String(255), nullable=False),
        sa.Column('lawyer_id', sa.Integer(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_number'),
        sa.ForeignKeyConstraint(['lawyer_id'], ['users.id'])
    )
    op.create_index('ix_cases_lawyer_id', 'cases', ['lawyer_id'])

    op.create_table('filings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('raw_content', sa.Text(), nullable=False),
        sa.Column('filing_date', sa.DateTime(), nullable=False),
        sa.Column('status', sa.Enum('new', 'analyzed', 'confirmed', 'discarded', name='filingstatusenum'), nullable=False, server_default='new'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'])
    )
    op.create_index('ix_filings_case_id', 'filings', ['case_id'])
    op.create_index('ix_filings_status', 'filings', ['status'])

    op.create_table('analyses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('filing_id', sa.Integer(), nullable=False),
        sa.Column('action_required', sa.Boolean(), nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('rag_examples_used', sa.JSON(), nullable=True),
        sa.Column('lawyer_confirmed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['filing_id'], ['filings.id'])
    )
    op.create_index('ix_analyses_filing_id', 'analyses', ['filing_id'])

    op.create_table('tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analysis_id', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('deadline_type', sa.Enum('request', 'follow_up', 'review', 'filing', name='deadlinetypeenum'), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('google_calendar_event_id', sa.String(255), nullable=True),
        sa.Column('lawyer_confirmed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'])
    )
    op.create_index('ix_tasks_analysis_id', 'tasks', ['analysis_id'])
    op.create_index('ix_tasks_due_date', 'tasks', ['due_date'])

    op.create_table('drafts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('chosen', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('edited_by_lawyer', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'])
    )
    op.create_index('ix_drafts_task_id', 'drafts', ['task_id'])

    op.create_table('example_bank',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('type', sa.Enum('analysis', 'document', name='exampletypeenum'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(1536), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('source_draft_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['source_draft_id'], ['drafts.id'])
    )
    op.create_index('ix_example_bank_type', 'example_bank', ['type'])
    op.execute('CREATE INDEX ix_example_bank_embedding ON example_bank USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)')


def downgrade() -> None:
    op.drop_index('ix_example_bank_embedding')
    op.drop_table('example_bank')
    op.drop_table('drafts')
    op.drop_table('tasks')
    op.drop_table('analyses')
    op.drop_table('filings')
    op.drop_table('cases')
    op.drop_table('users')
    op.execute('DROP EXTENSION IF EXISTS vector')
