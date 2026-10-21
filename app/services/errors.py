class ConflictError(Exception):
    """The request conflicts with existing state (maps to HTTP 409)."""
