// q3_threats_for_service.cypher
// Question: which ATT&CK techniques target a given service, and what is known
// about each?
//
// Follows (:Threat)-[:TARGETS]->(:Service), then pulls the vulnerabilities the
// technique exploits and the controls that mitigate it, so the answer to "what
// is auth-service exposed to" comes back with its countermeasures attached.
//
// Parameter: $service - a Service.name.

MATCH (t:Threat)-[:TARGETS]->(s:Service {name: $service})
OPTIONAL MATCH (t)-[:EXPLOITS]->(v:Vulnerability)
OPTIONAL MATCH (c:Control)-[:MITIGATES]->(t)
RETURN t.techniqueId              AS techniqueId,
       t.name                      AS technique,
       t.tactic                    AS tactic,
       collect(DISTINCT v.name)    AS exploitsVulnerabilities,
       collect(DISTINCT c.name)    AS mitigatedBy
ORDER BY techniqueId
