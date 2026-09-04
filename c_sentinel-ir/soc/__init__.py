"""
__init__.py - the SOC (Security Operations Centre) layer, Phase 2.

Collects the security events Phase 1 emits, detects suspicious patterns in them,
and raises alerts. Imports `libs/common` for the event schema and nothing else;
no Phase 1 service imports this package. Events flow one way: services emit, the
collector consumes.

Author: Colile
"""
