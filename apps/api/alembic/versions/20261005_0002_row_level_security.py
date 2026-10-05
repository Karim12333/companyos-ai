"""row level security and app role grants

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = [
    "organization_members",
    "organization_settings",
    "organization_preferences",
    "departments",
    "agents",
    "agent_relationships",
    "agent_tools",
    "agent_permissions",
    "projects",
    "objectives",
    "tasks",
    "task_dependencies",
    "task_runs",
    "workflow_runs",
    "agent_messages",
    "activity_events",
    "artifacts",
    "artifact_versions",
    "approvals",
    "approval_policies",
    "inbox_items",
    "notifications",
    "agent_feedback",
    "company_memory",
    "documents",
    "document_chunks",
    "integrations",
    "integration_credentials",
    "model_usage",
]

APP_ROLE = "companyos_app"


def upgrade() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION app_current_org() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting('app.org_id', true), '')::uuid $$"
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE AS "
        "$$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$"
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION app_rls_bypass() RETURNS boolean LANGUAGE sql STABLE AS "
        "$$ SELECT coalesce(current_setting('app.rls_bypass', true), 'off') = 'on' $$"
    )
    # Membership lookup that ignores RLS, used only inside the organizations policy
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_user_org_ids() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT organization_id FROM organization_members WHERE user_id = app_current_user()
        $$;
        """
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for table in TENANT_TABLES:
        if table == "organization_members":
            continue
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (organization_id = app_current_org() OR app_rls_bypass())
              WITH CHECK (organization_id = app_current_org() OR app_rls_bypass())
            """
        )

    op.execute(
        """
        CREATE POLICY tenant_isolation ON organization_members
          USING (organization_id = app_current_org() OR user_id = app_current_user() OR app_rls_bypass())
          WITH CHECK (organization_id = app_current_org() OR app_rls_bypass())
        """
    )

    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON organizations
          USING (id = app_current_org() OR id IN (SELECT app_user_org_ids()) OR app_rls_bypass())
          WITH CHECK (id = app_current_org() OR app_rls_bypass())
        """
    )

    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_logs
          USING (organization_id = app_current_org() OR app_rls_bypass())
          WITH CHECK (organization_id IS NULL OR organization_id = app_current_org() OR app_rls_bypass())
        """
    )

    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            GRANT USAGE ON SCHEMA public TO {APP_ROLE};
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
            GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO {APP_ROLE};
            REVOKE ALL ON alembic_version FROM {APP_ROLE};
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in [*TENANT_TABLES, "organizations", "audit_logs"]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS app_user_org_ids()")
    op.execute("DROP FUNCTION IF EXISTS app_rls_bypass()")
    op.execute("DROP FUNCTION IF EXISTS app_current_user()")
    op.execute("DROP FUNCTION IF EXISTS app_current_org()")
