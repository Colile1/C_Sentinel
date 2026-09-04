"""
test_load_topology.py - the topology source produces the right nodes and edges.

The facts that carry the step-17 verification: the real
`incident-service -[:DEPENDS_ON]-> asset-service` edge is emitted, every service
and endpoint is a `MERGE` (so a reload does not duplicate), and the seeded
users - including the bootstrap admin the seed file omits - get a role.

Runs without Neo4j.

Author: Colile
"""

from __future__ import annotations

from kg.loader.load_topology import topology


def _cyphers() -> list[str]:
    """Purpose: every statement the topology loader emits. Inputs: none.
    Output: a list of Cypher strings."""
    return [w.cypher for w in topology()]


def test_every_statement_is_a_merge():
    """A reload must not duplicate the graph, so no loader statement is a
    blind CREATE."""
    for cypher in _cyphers():
        assert "MERGE" in cypher
        assert "CREATE " not in cypher


def test_the_real_dependency_edge_is_emitted():
    """The one cross-service call in the system is in the graph."""
    joined = " || ".join(_cyphers())
    assert "DEPENDS_ON" in joined
    params = [w.parameters for w in topology() if "DEPENDS_ON" in w.cypher]
    assert params == [{"caller": "incident-service", "callee": "asset-service"}]


def test_all_four_services_are_present():
    """auth, incident, asset and the gateway are each a Service node."""
    names = {
        w.parameters["name"]
        for w in topology()
        if w.cypher.startswith("MERGE (s:Service")
    }
    assert names == {"auth-service", "incident-service", "asset-service", "api-gateway"}


def test_login_is_the_only_unprotected_endpoint():
    """Every endpoint node carries `protected`; only login is False."""
    unprotected = [
        w.parameters["path"]
        for w in topology()
        if w.cypher.startswith("MERGE (e:Endpoint") and w.parameters["protected"] is False
    ]
    assert unprotected == ["/api/v1/auth/login"]


def test_the_bootstrap_admin_is_loaded_with_a_role():
    """The seed file omits the admin (auth-service creates it); the loader adds
    it so the graph's user picture is complete."""
    admin_writes = [
        w for w in topology() if w.parameters.get("username") == "admin"
    ]
    assert admin_writes
    assert any(w.parameters.get("role") == "admin" for w in admin_writes)


def test_every_endpoint_has_an_exposes_edge_from_a_service():
    """Each Endpoint is reachable from its Service by `EXPOSES`."""
    exposes = [w for w in topology() if "EXPOSES" in w.cypher]
    exposed_paths = {w.parameters["path"] for w in exposes}
    endpoint_paths = {
        w.parameters["path"]
        for w in topology()
        if w.cypher.startswith("MERGE (e:Endpoint")
    }
    assert exposed_paths == endpoint_paths
