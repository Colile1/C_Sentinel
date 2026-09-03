"""
__init__.py - the incident-service application package.

Owns security incidents: what happened, how severe it is, who reported it,
which asset it affects, and where it sits in its lifecycle. The only service
that calls another - asset-service, through `app/services/asset_gateway.py`.

Author: Colile
"""
