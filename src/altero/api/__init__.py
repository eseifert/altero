"""HTTP layer.

This package is the only part of altero that knows about the web framework. It
extracts values from requests, calls :mod:`altero.services`, and turns domain
objects and errors into responses.
"""
