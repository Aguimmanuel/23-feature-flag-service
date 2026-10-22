"""Create flags, environment configurations, and audit history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "flags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("description", sa.String(500), server_default="", nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="flags_key_key"),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_-]{0,63}$'", name="flag_key_format"),
    )
    op.create_table(
        "flag_environments",
        sa.Column("flag_id", sa.UUID(), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("target_groups", postgresql.ARRAY(sa.Text()), server_default=sa.text("ARRAY[]::TEXT[]"), nullable=False),
        sa.Column("rollout_percentage", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("flag_id", "environment"),
        sa.ForeignKeyConstraint(["flag_id"], ["flags.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("environment IN ('development', 'staging', 'production')", name="valid_environment"),
        sa.CheckConstraint("rollout_percentage BETWEEN 0 AND 100", name="rollout_range"),
        sa.CheckConstraint("version >= 1", name="valid_version"),
        sa.CheckConstraint("cardinality(target_groups) <= 20", name="max_target_groups"),
        sa.CheckConstraint("array_position(target_groups, NULL) IS NULL", name="no_null_group_elements"),
        sa.CheckConstraint("cardinality(target_groups) = 0 OR array_ndims(target_groups) = 1", name="one_dimensional_groups"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("flag_id", sa.UUID(), nullable=False),
        sa.Column("environment", sa.String(16), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), server_default="shared-admin", nullable=False),
        sa.Column("before_state", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("after_state", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["flag_id"], ["flags.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("action IN ('FLAG_CREATED', 'FLAG_UPDATED', 'CONFIG_UPDATED', 'FLAG_ARCHIVED')", name="audit_action"),
        sa.CheckConstraint(
            "(action = 'CONFIG_UPDATED' AND environment IS NOT NULL "
            "AND environment IN ('development', 'staging', 'production')) "
            "OR (action <> 'CONFIG_UPDATED' AND environment IS NULL)",
            name="audit_environment",
        ),
    )
    op.create_index("audit_flag_time_idx", "audit_logs", ["flag_id", sa.text("created_at DESC"), sa.text("id DESC")])


def downgrade():
    op.drop_index("audit_flag_time_idx", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("flag_environments")
    op.drop_table("flags")
