"""
__init__.py - the shared infrastructure package for all Sentinel-IR services.

Config, typed errors, the security event schema, structured logging, the Consul
registry client and the resilient HTTP client. Contains no domain knowledge:
this package must never learn what an incident or an asset is.

Author: Colile
"""

__version__ = "0.1.0"
