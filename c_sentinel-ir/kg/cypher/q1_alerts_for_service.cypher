// q1_alerts_for_service.cypher
// Question: which alerts affect a given service, newest first?
//
// The service name is carried on the alert as `affectedService` (set by the
// rule when it raised the alert), so this is a direct match rather than a
// traversal - the fast path for "show me everything wrong with auth-service".
//
// Parameter: $service - a Service.name, e.g. "auth-service".

MATCH (a:Alert)
WHERE a.affectedService = $service
RETURN a.alertId        AS alertId,
       a.ruleName        AS ruleName,
       a.severity        AS severity,
       a.status          AS status,
       a.description      AS description,
       a.recommendedAction AS recommendedAction,
       a.timestamp        AS timestamp
ORDER BY a.timestamp DESC, a.alertId
