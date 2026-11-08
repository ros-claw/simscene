"""Bounded acquisition of explicitly selected source assets."""
from .glb import acquire_glb, inspect_glb
from .locks import copy_acquired_to_job

__all__ = ['acquire_glb', 'inspect_glb', 'copy_acquired_to_job']
