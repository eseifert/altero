"""Service layer.

Modules in this package hold the application's behaviour and must not import
from :mod:`altero.api` or from any web framework. They take a database session
and plain values, and signal failure with the domain errors in
:mod:`altero.errors`. Swapping the HTTP layer therefore leaves them untouched.
"""
