class ConcurrentModificationError(RuntimeError):
    """Raised when a revision-checked write targets stale data."""

    def __init__(self, entity: str, identity: int | str | None):
        self.entity = entity
        self.identity = identity
        super().__init__(f"{entity} {identity!r} changed in another connection")
