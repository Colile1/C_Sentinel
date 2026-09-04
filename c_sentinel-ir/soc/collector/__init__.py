"""
__init__.py - the event collector package, Phase 2 build step 14.

Reads the newline-delimited JSON event stream Phase 1 writes to stdout,
validates each line against `SecurityEvent`, and stores the events so the
detection rules can query them by user, source IP, service and time window.

Author: Colile
"""
