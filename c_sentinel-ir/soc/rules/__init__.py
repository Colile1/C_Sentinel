"""
__init__.py - the detection rules package.

Each rule is one file implementing `base.DetectionRule`. The rule and its
documentation are the same artefact: the specification requires a name, purpose,
input events, detection logic, severity, generated alert and response action for
every rule, and each of those is an attribute or method on the class rather than
a comment that can drift away from the code.

Author: Colile
"""
