"""Deprecated import location for the skills feature.

The implementation moved to :mod:`pydantic_deep.features.skills` (see the
CHANGELOG). This module (and its submodule shims) re-export the public names
for backward compatibility and will be removed in the next minor release.
Import from ``pydantic_deep.features.skills`` or the top-level ``pydantic_deep``
instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.skills import *  # noqa: F403

warnings.warn(
    "pydantic_deep.toolsets.skills has moved to pydantic_deep.features.skills; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
