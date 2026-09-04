// schema.cypher - constraints and indexes for the Sentinel-IR knowledge graph.
// Author: Colile
//
// Applied first by `python -m kg.loader.main`, before any loader runs. Every
// statement is idempotent: `IF NOT EXISTS` on the constraints, and Neo4j's own
// idempotence on `CREATE INDEX ... IF NOT EXISTS`. Re-running during a demo is
// safe.
//
// One uniqueness constraint per node label's natural key - the property the
// loaders `MERGE` on - which also creates a backing index. Extra indexes cover
// the properties the five demonstrated queries in kg/cypher/ filter by but do
// not match on identity.

// --- Uniqueness constraints (natural keys) --------------------------------
CREATE CONSTRAINT user_id IF NOT EXISTS
  FOR (n:User) REQUIRE n.username IS UNIQUE;
CREATE CONSTRAINT service_name IF NOT EXISTS
  FOR (n:Service) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT endpoint_path IF NOT EXISTS
  FOR (n:Endpoint) REQUIRE n.path IS UNIQUE;
CREATE CONSTRAINT asset_name IF NOT EXISTS
  FOR (n:Asset) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS
  FOR (n:Event) REQUIRE n.eventId IS UNIQUE;
CREATE CONSTRAINT alert_id IF NOT EXISTS
  FOR (n:Alert) REQUIRE n.alertId IS UNIQUE;
CREATE CONSTRAINT incident_id IF NOT EXISTS
  FOR (n:Incident) REQUIRE n.incidentId IS UNIQUE;
CREATE CONSTRAINT threat_id IF NOT EXISTS
  FOR (n:Threat) REQUIRE n.techniqueId IS UNIQUE;
CREATE CONSTRAINT control_id IF NOT EXISTS
  FOR (n:Control) REQUIRE n.controlId IS UNIQUE;
CREATE CONSTRAINT vulnerability_id IF NOT EXISTS
  FOR (n:Vulnerability) REQUIRE n.vulnId IS UNIQUE;
CREATE CONSTRAINT role_name IF NOT EXISTS
  FOR (n:Role) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT document_id IF NOT EXISTS
  FOR (n:Document) REQUIRE n.docId IS UNIQUE;

// --- Query-supporting indexes ------------------------------------------------
// q1 / q2 filter alerts by severity and status.
CREATE INDEX alert_severity IF NOT EXISTS FOR (n:Alert) ON (n.severity);
CREATE INDEX alert_status IF NOT EXISTS FOR (n:Alert) ON (n.status);
// q1 / q3 join through the affected service name carried on the alert.
CREATE INDEX alert_affected_service IF NOT EXISTS
  FOR (n:Alert) ON (n.affectedService);
// events are looked up by correlation id when tracing one workflow.
CREATE INDEX event_correlation IF NOT EXISTS
  FOR (n:Event) ON (n.correlationId);
CREATE INDEX event_type IF NOT EXISTS FOR (n:Event) ON (n.eventType);
