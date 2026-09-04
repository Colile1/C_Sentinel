// q4_controls_for_alert.cypher
// Question: for a given alert, what should be done about it - which controls
// mitigate the threat it indicates, and which runbooks cover the response?
//
// This is the query the RAG layer runs to answer "what should be done?". The
// path is (:Alert)-[:INDICATES]->(:Threat)<-[:MITIGATES]-(:Control), with the
// response Documents pulled alongside.
//
// Parameter: $alertId - an Alert.alertId.

MATCH (a:Alert {alertId: $alertId})-[:INDICATES]->(t:Threat)
OPTIONAL MATCH (c:Control)-[:MITIGATES]->(t)
OPTIONAL MATCH (d:Document)-[:SUPPORTS_RESPONSE_TO]->(t)
RETURN a.alertId                       AS alertId,
       a.ruleName                       AS ruleName,
       t.techniqueId                    AS techniqueId,
       t.name                           AS technique,
       collect(DISTINCT c.name)         AS controls,
       collect(DISTINCT d.title)        AS runbooks,
       a.recommendedAction              AS ruleRecommendedAction
