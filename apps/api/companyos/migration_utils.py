from alembic import op

APP_ROLE = "companyos_app"


def enable_tenant_rls(table: str) -> None:
    """Same tenant isolation policy as every other tenant table (see migration 0002)."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
          USING (organization_id = app_current_org() OR app_rls_bypass())
          WITH CHECK (organization_id = app_current_org() OR app_rls_bypass())
        """
    )
    grant_app_role(table)


def grant_app_role(table: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE};
          END IF;
        END $$;
        """
    )


def drop_tenant_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
