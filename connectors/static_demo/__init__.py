"""Trivial reference connector: a hardcoded two-object "source".

Exists to prove the SDK harness end-to-end (manifest → introspect →
emission → CLI) before any real source exists, and to stage failure
injection for the S-6 all-or-nothing tests. It is also the template
tasks 1.2-1.4 copy: manifest + config schema + one MetadataProvider.
"""
