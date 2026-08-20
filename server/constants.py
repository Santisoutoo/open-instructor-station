"""Constants shared across ``server/*_routes.py`` modules.

This module has ZERO imports of its own, and that is the point: every route
module already imports ``server.deps`` and several import each other's
response models, but none of them needs a dataref name, a capability flag or
an HTTP status code that another route module owns. Route modules import
*from* here; nothing here imports *from* them, so the import graph among
``server/*_routes.py`` stays one-way regardless of which modules end up
depending on which.
"""

from __future__ import annotations

__all__ = ["CAPABILITY_UNAVAILABLE_STATUS"]

#: Status for "the active adapter cannot do this". 501 rather than 4xx: the
#: request is well-formed, the *server* has no implementation behind it. The
#: UI is expected to have disabled the control long before it gets here —
#: reaching this response means a caller ignored a manifest/capabilities
#: endpoint.
CAPABILITY_UNAVAILABLE_STATUS = 501
