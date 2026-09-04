// q5_dependency_impact.cypher
// Question: if a given service fails, which other services are affected -
// directly or transitively?
//
// The blast radius. Follows :DEPENDS_ON *against* its direction with a
// variable-length pattern: every service that depends on $service, and every
// service that depends on one of those, and so on. On this application the one
// real edge is incident-service -> asset-service, so failing asset-service
// returns incident-service.
//
// Parameter: $service - the Service.name that is failing.

// The `*1..10` upper bound keeps the planner happy; the real graph has one
// DEPENDS_ON edge, and no sane microservice topology is ten deep.
MATCH (failing:Service {name: $service})
MATCH path = (dependent:Service)-[:DEPENDS_ON*1..10]->(failing)
WITH dependent, min(length(path)) AS hops
RETURN dependent.name AS impactedService, hops
ORDER BY hops, impactedService
