"""PostgreSQL tables and constraints. Migrations own schema creation."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    SmallInteger, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Flag(Base):
    __tablename__ = "flags"
    __table_args__ = (
        UniqueConstraint("key", name="flags_key_key"),
        CheckConstraint("key ~ '^[a-z][a-z0-9_-]{0,63}$'", name="flag_key_format"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    environments: Mapped[list["FlagEnvironment"]] = relationship(
        back_populates="flag", passive_deletes="all",
    )


class FlagEnvironment(Base):
    __tablename__ = "flag_environments"
    __table_args__ = (
        CheckConstraint("environment IN ('development', 'staging', 'production')", name="valid_environment"),
        CheckConstraint("rollout_percentage BETWEEN 0 AND 100", name="rollout_range"),
        CheckConstraint("version >= 1", name="valid_version"),
        CheckConstraint("cardinality(target_groups) <= 20", name="max_target_groups"),
        CheckConstraint("array_position(target_groups, NULL) IS NULL", name="no_null_group_elements"),
        CheckConstraint("cardinality(target_groups) = 0 OR array_ndims(target_groups) = 1", name="one_dimensional_groups"),
    )

    flag_id: Mapped[UUID] = mapped_column(ForeignKey("flags.id", ondelete="RESTRICT"), primary_key=True)
    environment: Mapped[str] = mapped_column(String(16), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    target_groups: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=text("ARRAY[]::TEXT[]"))
    rollout_percentage: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    flag: Mapped[Flag] = relationship(back_populates="environments")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "action IN ('FLAG_CREATED', 'FLAG_UPDATED', 'CONFIG_UPDATED', 'FLAG_ARCHIVED')",
            name="audit_action",
        ),
        CheckConstraint(
            "(action = 'CONFIG_UPDATED' AND environment IS NOT NULL "
            "AND environment IN ('development', 'staging', 'production')) "
            "OR (action <> 'CONFIG_UPDATED' AND environment IS NULL)",
            name="audit_environment",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    flag_id: Mapped[UUID] = mapped_column(ForeignKey("flags.id", ondelete="RESTRICT"))
    environment: Mapped[str | None] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(64), default="shared-admin", server_default="shared-admin")
    before_state: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    after_state: Mapped[dict] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("audit_flag_time_idx", AuditLog.flag_id, AuditLog.created_at.desc(), AuditLog.id.desc())
