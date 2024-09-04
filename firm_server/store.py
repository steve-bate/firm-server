import logging
import os
from abc import ABC, abstractmethod
from typing import final

from firm.interfaces import ResourceStore
from firm.store.file import FileResourceStore
from firm.store.prefixstore import (
    PrefixAwareResourceStore,
    PrefixAwareResourceStoreWithFetch,
)
from firm_ld.store import RdfDataSet, RdfResourceStore

from firm_server.adapters import HttpxTransport
from firm_server.config import FileStoreConfig, ServerConfig
from firm_server.exceptions import ServerException

log = logging.getLogger(__name__)


class StoreDriver(ABC):
    def __init__(self, name: str) -> None:
        self.name = name
        self._store = None

    @property
    def store(self) -> ResourceStore:
        if not self._store:
            raise ServerException("Resource store not initialized", logging.CRITICAL)

        return self._store

    @final
    def open(self, config: ServerConfig) -> ResourceStore:
        self._store = self._open(config)
        return self._store

    @abstractmethod
    def _open(self, config: ServerConfig) -> ResourceStore:
        ...

    @final
    def close(self):
        if self._store and hasattr(self.store, "close"):
            self._store.close()


class RdfStoreDriver(StoreDriver):
    def __init__(self) -> None:
        super().__init__("rdf")

    def _open(self, config: ServerConfig) -> ResourceStore:
        if not config.store.rdf:
            raise ServerException("RDF store configuration missing", logging.CRITICAL)
        graph_path = config.store.rdf.path
        log.info("Opening RDF graph store at %s", graph_path)
        RdfDataSet.configure("Oxigraph", [graph_path])
        return RdfResourceStore(RdfDataSet.VALUE)


class FileSystemStoreDriver(StoreDriver):
    def __init__(self) -> None:
        super().__init__("filesystem")

    @classmethod
    def _ensure_dir_exists(cls, d: str):
        if not os.path.exists(d):
            os.makedirs(d)
        if not os.path.isdir(d):
            raise ServerException(
                f"Path '{d}' exists but is not a directory", logging.CRITICAL
            )

    @classmethod
    def _ensure_dirs_exist(cls, config: FileStoreConfig) -> None:
        cls._ensure_dir_exists(os.path.join(config.path, config.tenants_subdir))
        cls._ensure_dir_exists(os.path.join(config.path, config.remote_subdir))
        cls._ensure_dir_exists(os.path.join(config.path, config.private_subdir))

    def _open(self, config: ServerConfig) -> ResourceStore:
        if not config.store.filesystem:
            raise ServerException(
                "Filesystem store configuration missing", logging.CRITICAL
            )
        self._ensure_dirs_exist(config.store.filesystem)
        fs = config.store.filesystem
        tenant_store = FileResourceStore(
            os.path.join(
                fs.path,
                fs.tenants_subdir,
            )
        )
        tenant_stores = {
            tenant_prefix: tenant_store for tenant_prefix in config.tenants
        }
        log.debug("tenant stores: %s", tenant_stores)
        return PrefixAwareResourceStoreWithFetch(
            PrefixAwareResourceStore(
                tenant_stores,
                FileResourceStore(os.path.join(fs.path, fs.remote_subdir)),
                FileResourceStore(os.path.join(fs.path, fs.private_subdir)),
            ),
        ).with_transport(lambda store: HttpxTransport(store))


STORE_DRIVERS = {
    driver.name: driver for driver in [RdfStoreDriver(), FileSystemStoreDriver()]
}
