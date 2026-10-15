// q6_incidents_and_alerts.cypher
// Question: which incidents group which alerts, and what asset is each
// incident raised against?
//
// An incident CONTAINS the HIGH or CRITICAL alerts whose evidence fell in the
// window before it was raised (kg/loader/load_events.py), so this answers
// "which incidents are linked to repeated failed logins?" and "which alerts
// may indicate a wider security incident?" from one traversal.
//
// No parameters.

MATCH (i:Incident)
OPTIONAL MATCH (i)-[:AFFECTS]->(asset:Asset)
OPTIONAL MATCH (i)-[:CONTAINS]->(a:Alert)
RETURN i.incidentId                 AS incidentId,
       i.severity                   AS severity,
       i.title                      AS title,
       i.reportedBy                 AS reportedBy,
       asset.name                   AS asset,
       collect(DISTINCT {alertId: a.alertId, ruleName: a.ruleName}) AS alerts
ORDER BY incidentId
