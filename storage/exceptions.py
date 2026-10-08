class StorageError(Exception):
    """Base storage exception."""


class CollectionNotFound(StorageError):
    pass


class DuplicateCollection(StorageError):
    pass


class EmbeddingStoreError(StorageError):
    pass
