"""
load_security_knowledge.py - source 3 of 3: what is *known* about the threats.

MITRE ATT&CK techniques, the weaknesses they exploit, the controls that mitigate
them, and the response runbooks - plus the `INDICATES` edge that connects each
detection rule's alerts to the technique that rule detects.

**T1110 Brute Force** and its four sub-techniques are the worked example the
specification requires and are certain. One further technique is loaded per
other detection rule so every rule's alerts have a threat to point at (the open
decision in `DECISIONS.md`, closed here):

  Multiple Failed Logins      -> T1110      Brute Force
  Unauthorised Endpoint Access -> T1078     Valid Accounts
  Abnormal Request Rate       -> T1498     Network Denial of Service
  Service Failure             -> T1499     Endpoint Denial of Service

`knowledge()` is pure; a test asserts the `Write` list and `main` applies it.

Author: Colile
"""

from __future__ import annotations

from kg.loader.writes import Write

_LOADER = "security-knowledge"

# Techniques. `rule` is the detection-rule name whose alerts INDICATE this
# technique; None for a sub-technique that is loaded for completeness but that
# no rule maps to directly.
_THREATS = (
    {"techniqueId": "T1110", "name": "Brute Force",
     "tactic": "Credential Access",
     "description": "Adversaries systematically guess credentials for accounts "
                    "when passwords are unknown or hashes are obtained.",
     "rule": "Multiple Failed Logins"},
    {"techniqueId": "T1110.001", "name": "Password Guessing",
     "tactic": "Credential Access",
     "description": "Guessing passwords against a login service without prior "
                    "knowledge, using common or default values.",
     "rule": None},
    {"techniqueId": "T1110.002", "name": "Password Cracking",
     "tactic": "Credential Access",
     "description": "Recovering plaintext from captured password hashes offline.",
     "rule": None},
    {"techniqueId": "T1110.003", "name": "Password Spraying",
     "tactic": "Credential Access",
     "description": "Trying one or a few common passwords against many accounts "
                    "to avoid per-account lockouts.",
     "rule": None},
    {"techniqueId": "T1110.004", "name": "Credential Stuffing",
     "tactic": "Credential Access",
     "description": "Using username/password pairs breached elsewhere against "
                    "this login service.",
     "rule": None},
    {"techniqueId": "T1078", "name": "Valid Accounts",
     "tactic": "Defense Evasion",
     "description": "Using legitimate credentials to access resources beyond "
                    "the account's authorised scope.",
     "rule": "Unauthorised Endpoint Access"},
    {"techniqueId": "T1498", "name": "Network Denial of Service",
     "tactic": "Impact",
     "description": "Exhausting a service's request capacity with a flood of "
                    "traffic from one or more sources.",
     "rule": "Abnormal Request Rate"},
    {"techniqueId": "T1499", "name": "Endpoint Denial of Service",
     "tactic": "Impact",
     "description": "Overwhelming a specific service until it degrades or its "
                    "dependencies fail.",
     "rule": "Service Failure"},
)

# Sub-technique -> parent, as `EXPLOITS`-adjacent structure via a shared
# vulnerability rather than a MITRE subtechnique edge (kept simple for the demo).
_SUBTECHNIQUES = (
    ("T1110.001", "T1110"),
    ("T1110.002", "T1110"),
    ("T1110.003", "T1110"),
    ("T1110.004", "T1110"),
)

# Weaknesses the techniques rely on.
_VULNERABILITIES = (
    {"vulnId": "SENTINEL-VULN-001", "name": "No account lockout",
     "description": "auth-service applied no lockout after repeated failures at "
                    "the time these events were captured, so guessing is "
                    "rate-limited only by the gateway.",
     "threats": ("T1110", "T1110.001", "T1110.003", "T1110.004")},
    {"vulnId": "SENTINEL-VULN-002", "name": "Single-factor authentication",
     "description": "Login requires only a password, so a correct guess is a "
                    "full compromise.",
     "threats": ("T1110", "T1078")},
    {"vulnId": "SENTINEL-VULN-003", "name": "Unbounded per-caller throughput",
     "description": "Beyond the gateway rate limit there is no per-service "
                    "admission control, so a burst that gets through degrades "
                    "the upstream.",
     "threats": ("T1498", "T1499")},
)

# Controls, and the techniques each mitigates.
_CONTROLS = (
    {"controlId": "CTRL-LOCKOUT", "name": "Account lockout",
     "description": "Lock an account for a cooldown period after a threshold of "
                    "consecutive failed logins.",
     "threats": ("T1110", "T1110.001", "T1110.003")},
    {"controlId": "CTRL-MFA", "name": "Multi-factor authentication",
     "description": "Require a second factor so a guessed or stuffed password "
                    "is not sufficient to authenticate.",
     "threats": ("T1110", "T1110.004", "T1078")},
    {"controlId": "CTRL-PWRESET", "name": "Forced password reset",
     "description": "Invalidate the credential and require a reset once an "
                    "account is suspected compromised.",
     "threats": ("T1110", "T1078")},
    {"controlId": "CTRL-RATELIMIT", "name": "Gateway rate limiting",
     "description": "Cap requests per consumer at the gateway so a flood is "
                    "refused before it reaches a service.",
     "threats": ("T1498", "T1499")},
)

# Response runbooks.
_DOCUMENTS = (
    {"docId": "RB-BRUTE-FORCE", "title": "Runbook: brute-force response",
     "kind": "runbook", "describes": "CTRL-LOCKOUT",
     "responds_to": ("T1110",)},
    {"docId": "RB-CRED-COMPROMISE", "title": "Runbook: suspected account "
     "compromise", "kind": "runbook", "describes": "CTRL-PWRESET",
     "responds_to": ("T1110", "T1078")},
    {"docId": "RB-DOS", "title": "Runbook: service under load",
     "kind": "runbook", "describes": "CTRL-RATELIMIT",
     "responds_to": ("T1498", "T1499")},
)

# The service each technique TARGETS in this application.
_THREAT_TARGETS = (
    ("T1110", "auth-service"),
    ("T1078", "auth-service"),
    ("T1498", "api-gateway"),
    ("T1499", "incident-service"),
)


def _merge_threats() -> list[Write]:
    """Purpose: every Threat node. Inputs: none. Output: a list of `Write`."""
    return [
        Write(
            "MERGE (t:Threat {techniqueId: $techniqueId}) SET "
            "t.name = $name, t.tactic = $tactic, t.description = $description",
            {k: threat[k] for k in ("techniqueId", "name", "tactic", "description")},
            _LOADER,
        )
        for threat in _THREATS
    ]


def _merge_subtechniques() -> list[Write]:
    """Purpose: a `SUBTECHNIQUE_OF`-style link, modelled as the sub-technique
    INDICATES-adjacent to its parent via TARGETS sharing. Kept as an explicit
    parent edge. Inputs: none. Output: a list of `Write`."""
    return [
        Write(
            "MATCH (child:Threat {techniqueId: $child}) "
            "MATCH (parent:Threat {techniqueId: $parent}) "
            "MERGE (child)-[:SUBTECHNIQUE_OF]->(parent)",
            {"child": child, "parent": parent},
            _LOADER,
        )
        for child, parent in _SUBTECHNIQUES
    ]


def _merge_threat_targets() -> list[Write]:
    """Purpose: the `TARGETS` edge from each technique to the service it is
    aimed at. Inputs: none. Output: a list of `Write`."""
    return [
        Write(
            "MATCH (t:Threat {techniqueId: $technique}) "
            "MERGE (s:Service {name: $service}) "
            "MERGE (t)-[:TARGETS]->(s)",
            {"technique": technique, "service": service},
            _LOADER,
        )
        for technique, service in _THREAT_TARGETS
    ]


def _merge_vulnerabilities() -> list[Write]:
    """Purpose: Vulnerability nodes and the `EXPLOITS` edges into them.
    Inputs: none. Output: a list of `Write`."""
    writes: list[Write] = []
    for vuln in _VULNERABILITIES:
        writes.append(
            Write(
                "MERGE (v:Vulnerability {vulnId: $vulnId}) SET "
                "v.name = $name, v.description = $description",
                {k: vuln[k] for k in ("vulnId", "name", "description")},
                _LOADER,
            )
        )
        for technique in vuln["threats"]:
            writes.append(
                Write(
                    "MATCH (t:Threat {techniqueId: $technique}) "
                    "MATCH (v:Vulnerability {vulnId: $vulnId}) "
                    "MERGE (t)-[:EXPLOITS]->(v)",
                    {"technique": technique, "vulnId": vuln["vulnId"]},
                    _LOADER,
                )
            )
    return writes


def _merge_controls() -> list[Write]:
    """Purpose: Control nodes and the `MITIGATES` edges to the techniques.
    Inputs: none. Output: a list of `Write`."""
    writes: list[Write] = []
    for control in _CONTROLS:
        writes.append(
            Write(
                "MERGE (c:Control {controlId: $controlId}) SET "
                "c.name = $name, c.description = $description",
                {k: control[k] for k in ("controlId", "name", "description")},
                _LOADER,
            )
        )
        for technique in control["threats"]:
            writes.append(
                Write(
                    "MATCH (c:Control {controlId: $controlId}) "
                    "MATCH (t:Threat {techniqueId: $technique}) "
                    "MERGE (c)-[:MITIGATES]->(t)",
                    {"controlId": control["controlId"], "technique": technique},
                    _LOADER,
                )
            )
    return writes


def _merge_documents() -> list[Write]:
    """Purpose: Document nodes with `DESCRIBES` and `SUPPORTS_RESPONSE_TO`
    edges. Inputs: none. Output: a list of `Write`."""
    writes: list[Write] = []
    for doc in _DOCUMENTS:
        writes.append(
            Write(
                "MERGE (d:Document {docId: $docId}) SET "
                "d.title = $title, d.kind = $kind",
                {k: doc[k] for k in ("docId", "title", "kind")},
                _LOADER,
            )
        )
        writes.append(
            Write(
                "MATCH (d:Document {docId: $docId}) "
                "MATCH (c:Control {controlId: $control}) "
                "MERGE (d)-[:DESCRIBES]->(c)",
                {"docId": doc["docId"], "control": doc["describes"]},
                _LOADER,
            )
        )
        for technique in doc["responds_to"]:
            writes.append(
                Write(
                    "MATCH (d:Document {docId: $docId}) "
                    "MATCH (t:Threat {techniqueId: $technique}) "
                    "MERGE (d)-[:SUPPORTS_RESPONSE_TO]->(t)",
                    {"docId": doc["docId"], "technique": technique},
                    _LOADER,
                )
            )
    return writes


def rule_threat_links() -> list[Write]:
    """
    Purpose: the `INDICATES` edge from every alert a rule raised to the technique
             that rule detects - matched by the alert's `ruleName`, so it wires
             alerts loaded by `load_events` without either loader importing the
             other.
    Inputs:  none.
    Output:  a list of `Write`, one per rule that maps to a technique.
    """
    return [
        Write(
            "MATCH (a:Alert {ruleName: $ruleName}) "
            "MATCH (t:Threat {techniqueId: $technique}) "
            "MERGE (a)-[:INDICATES]->(t)",
            {"ruleName": threat["rule"], "technique": threat["techniqueId"]},
            _LOADER,
        )
        for threat in _THREATS
        if threat["rule"] is not None
    ]


def knowledge() -> list[Write]:
    """
    Purpose: the whole security-knowledge source as idempotent writes -
             techniques, sub-technique links, threat targets, vulnerabilities,
             controls, runbooks, and the rule-to-technique `INDICATES` edges.
    Inputs:  none.
    Output:  a list of `Write`, nodes before the edges that MATCH them.
    """
    return [
        *_merge_threats(),
        *_merge_subtechniques(),
        *_merge_threat_targets(),
        *_merge_vulnerabilities(),
        *_merge_controls(),
        *_merge_documents(),
        *rule_threat_links(),
    ]
