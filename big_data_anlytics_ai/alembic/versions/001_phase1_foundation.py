"""Phase 1 foundation: users, workspaces, auth, data connections

Revision ID: 001_phase1
Revises:
Create Date: 2026-06-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_phase1"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

oauth_provider = postgresql.ENUM("google", name="oauthprovider", create_type=False)
workspace_plano = postgresql.ENUM(
    "starter", "pro", "enterprise", name="workspaceplano", create_type=False
)
workspace_member_papel = postgresql.ENUM(
    "admin", "member", name="workspacememberpapel", create_type=False
)
data_connection_tipo = postgresql.ENUM(
    "postgres", "sqlserver", name="dataconnectiontipo", create_type=False
)
data_connection_status = postgresql.ENUM(
    "ativo", "erro", "testando", name="dataconnectionstatus", create_type=False
)
profiling_status = postgresql.ENUM(
    "pendente",
    "em_andamento",
    "concluido",
    "falhou",
    name="profilingstatus",
    create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE TYPE oauthprovider AS ENUM ('google')")
    op.execute(
        "CREATE TYPE workspaceplano AS ENUM ('starter', 'pro', 'enterprise')"
    )
    op.execute("CREATE TYPE workspacememberpapel AS ENUM ('admin', 'member')")
    op.execute("CREATE TYPE dataconnectiontipo AS ENUM ('postgres', 'sqlserver')")
    op.execute(
        "CREATE TYPE dataconnectionstatus AS ENUM ('ativo', 'erro', 'testando')"
    )
    op.execute(
        "CREATE TYPE profilingstatus AS ENUM "
        "('pendente', 'em_andamento', 'concluido', 'falhou')"
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("data_source_type", sa.String(), nullable=False),
        sa.Column("data_source_meta", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_id"), "tasks", ["id"], unique=False)

    op.create_table(
        "llm_interactions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model_answer", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_interactions_id"), "llm_interactions", ["id"], unique=False)
    op.create_index(
        op.f("ix_llm_interactions_task_id"), "llm_interactions", ["task_id"], unique=False
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.Column("oauth_provider", oauth_provider, nullable=True),
        sa.Column("oauth_id", sa.String(length=255), nullable=True),
        sa.Column("idioma_ui_preferido", sa.String(length=10), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_oauth_id"), "users", ["oauth_id"], unique=False)

    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nome", sa.String(length=255), nullable=False),
        sa.Column("plano", workspace_plano, nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("limite_mensagens_mes", sa.Integer(), nullable=False),
        sa.Column("tokens_consumidos_mes_atual", sa.Integer(), nullable=False),
        sa.Column("periodo_referencia", sa.String(length=7), nullable=False),
        sa.Column("exibir_pii_liberado", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "workspace_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("papel", workspace_member_papel, nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "workspace_id", name="uq_workspace_member"),
    )
    op.create_index(
        op.f("ix_workspace_members_workspace_id"),
        "workspace_members",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "workspace_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("papel", workspace_member_papel, nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_workspace_invites_token_hash"),
        "workspace_invites",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_workspace_invites_workspace_id"),
        "workspace_invites",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "data_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nome_amigavel", sa.String(length=255), nullable=False),
        sa.Column("tipo", data_connection_tipo, nullable=False),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("porta", sa.Integer(), nullable=True),
        sa.Column("database", sa.String(length=255), nullable=True),
        sa.Column("usuario", sa.String(length=255), nullable=True),
        sa.Column("senha_criptografada", sa.Text(), nullable=True),
        sa.Column("connection_string_criptografada", sa.Text(), nullable=True),
        sa.Column("status", data_connection_status, nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.Column("ultima_data_profiling", sa.DateTime(), nullable=True),
        sa.Column("status_profiling", profiling_status, nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_data_connections_workspace_id"),
        "data_connections",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_refresh_tokens_token_hash"),
        "refresh_tokens",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_password_reset_tokens_token_hash"),
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("password_reset_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("data_connections")
    op.drop_table("workspace_invites")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("users")
    op.drop_index(op.f("ix_llm_interactions_task_id"), table_name="llm_interactions")
    op.drop_index(op.f("ix_llm_interactions_id"), table_name="llm_interactions")
    op.drop_table("llm_interactions")
    op.drop_index(op.f("ix_tasks_id"), table_name="tasks")
    op.drop_table("tasks")

    op.execute("DROP TYPE IF EXISTS profilingstatus")
    op.execute("DROP TYPE IF EXISTS dataconnectionstatus")
    op.execute("DROP TYPE IF EXISTS dataconnectiontipo")
    op.execute("DROP TYPE IF EXISTS workspacememberpapel")
    op.execute("DROP TYPE IF EXISTS workspaceplano")
    op.execute("DROP TYPE IF EXISTS oauthprovider")
