-- deploy/postgres/init/incident-db.sql
--
-- Runs once, on first start of the incident-db container, before it accepts
-- connections (postgres:16 executes every *.sql in /docker-entrypoint-initdb.d
-- against the database named by POSTGRES_DB). The database, its owner and the
-- owner's password are already created by the image from the container's
-- POSTGRES_* environment; this file is the explicit, per-database record D-04
-- calls for, and the place any incident-specific grant or extension would go.
--
-- incident-service is the only service with a credential for this database.
-- No other service may connect here - the Database-per-Service pattern.

-- The application creates its own tables at startup (SQLAlchemy create_all in
-- app/database.py), so no schema is defined here yet. Alembic owns schema
-- change once there is a second revision.

SELECT 'sentinel-ir incident-db initialised' AS status;
