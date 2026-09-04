// q2_users_high_severity.cypher
// Question: which users are linked to HIGH or CRITICAL alerts, and through
// which events?
//
// The path is the point: a user TRIGGERED an event, and that event
// CREATED_ALERT an alert the rule rated HIGH or CRITICAL. This is the query
// that turns "an account is under attack" into a name and the evidence for it.
//
// No parameters.

MATCH (u:User)-[:TRIGGERED]->(e:Event)-[:CREATED_ALERT]->(a:Alert)
WHERE a.severity IN ["HIGH", "CRITICAL"]
RETURN u.username           AS username,
       u.role               AS role,
       a.ruleName           AS ruleName,
       a.severity           AS severity,
       collect(DISTINCT e.eventId) AS evidenceEvents,
       count(DISTINCT a)    AS alertCount
ORDER BY alertCount DESC, username
