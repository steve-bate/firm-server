import logging
import os

from firm.interfaces import ResourceStore
from firm.store.file import FileResourceStore
from firm.store.prefixstore import (
    PrefixAwareResourceStore,
    PrefixAwareResourceStoreWithFetch,
)

from firm_server.adapters import HttpxTransport
from firm_server.config import FileStoreConfig, ServerConfig
from firm_server.exceptions import ServerException

log = logging.getLogger(__name__)

_STORE: ResourceStore | None = None


def _ensure_dir_exists(d: str):
    if not os.path.exists(d):
        os.makedirs(d)
    if not os.path.isdir(d):
        raise ServerException(
            f"Path '{d}' exists but is not a directory", logging.CRITICAL
        )


def _ensure_dirs_exist(config: FileStoreConfig) -> None:
    _ensure_dir_exists(os.path.join(config.path, config.tenants_subdir))
    _ensure_dir_exists(os.path.join(config.path, config.remote_subdir))
    _ensure_dir_exists(os.path.join(config.path, config.private_subdir))


def initialize_store(config: ServerConfig) -> ResourceStore:
    global _STORE
    _ensure_dirs_exist(config.store)
    tenant_store = FileResourceStore(
        os.path.join(
            config.store.path,
            config.store.tenants_subdir,
        )
    )
    tenant_stores = {tenant_prefix: tenant_store for tenant_prefix in config.tenants}
    log.debug("tenant stores: %s", tenant_stores)
    _STORE = PrefixAwareResourceStoreWithFetch(
        PrefixAwareResourceStore(
            tenant_stores,
            FileResourceStore(
                os.path.join(config.store.path, config.store.remote_subdir)
            ),
            FileResourceStore(
                os.path.join(config.store.path, config.store.private_subdir)
            ),
        ),
    ).with_transport(lambda store: HttpxTransport(store))
    return _STORE


def get_store():
    global _STORE
    if not _STORE:
        raise ServerException("Resource store not initialized", logging.CRITICAL)
    return _STORE
