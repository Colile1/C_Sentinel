"""
test_load_security_knowledge.py - the MITRE source, and the three-hop reach.

The step-17 verification for this source: T1110 Brute Force is present with its
four sub-techniques, account lockout / MFA / password reset all `MITIGATES`
T1110, and a *Multiple Failed Logins* alert reaches a control in three hops
`(:Alert)-[:INDICATES]->(:Threat)<-[:MITIGATES]-(:Control)` - checked here by
following the write list rather than a live graph.

Runs without Neo4j.

Author: Colile
"""

from __future__ import annotations

from kg.loader.load_security_knowledge import knowledge, rule_threat_links


def _threat_ids() -> set[str]:
    """Purpose: every techniqueId the loader MERGEs. Inputs: none.
    Output: a set of ids."""
    return {
        w.parameters["techniqueId"]
        for w in knowledge()
        if w.cypher.startswith("MERGE (t:Threat")
    }


def test_t1110_and_its_four_subtechniques_are_present():
    """The worked example the specification names, in full."""
    ids = _threat_ids()
    assert "T1110" in ids
    for suffix in ("001", "002", "003", "004"):
        assert f"T1110.{suffix}" in ids


def test_the_three_named_controls_mitigate_t1110():
    """Account lockout, MFA and password reset each MITIGATES Brute Force."""
    mitigators = {
        w.parameters["controlId"]
        for w in knowledge()
        if "MITIGATES" in w.cypher and w.parameters.get("technique") == "T1110"
    }
    assert {"CTRL-LOCKOUT", "CTRL-MFA", "CTRL-PWRESET"} <= mitigators


def test_every_detection_rule_maps_to_a_technique():
    """`INDICATES` needs a target for every rule, so no alert is a dead end."""
    rules = {w.parameters["ruleName"] for w in rule_threat_links()}
    assert rules == {
        "Multiple Failed Logins",
        "Unauthorised Endpoint Access",
        "Abnormal Request Rate",
        "Service Failure",
    }


def test_a_failed_login_alert_reaches_a_control_in_three_hops():
    """Alert -INDICATES-> T1110 <-MITIGATES- Control, traced through the writes."""
    indicates = {
        w.parameters["technique"]
        for w in rule_threat_links()
        if w.parameters["ruleName"] == "Multiple Failed Logins"
    }
    assert indicates == {"T1110"}

    controls_for_t1110 = {
        w.parameters["controlId"]
        for w in knowledge()
        if "MITIGATES" in w.cypher and w.parameters.get("technique") == "T1110"
    }
    assert controls_for_t1110  # the third hop lands somewhere


def test_t1110_targets_auth_service():
    """The technique is aimed at the login service in this application."""
    targets = {
        (w.parameters["technique"], w.parameters["service"])
        for w in knowledge()
        if "TARGETS" in w.cypher
    }
    assert ("T1110", "auth-service") in targets


def test_every_statement_is_a_merge():
    """Reloading the knowledge source must not duplicate it."""
    for write in knowledge():
        assert "MERGE" in write.cypher
        assert "CREATE " not in write.cypher
