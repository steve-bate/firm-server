import logging

from firm.interfaces import ResourceStore
from firm_ld.store import RdfDataSet, RdfResourceStore

from firm_server.config import ServerConfig
from firm_server.exceptions import ServerException

log = logging.getLogger(__name__)

_STORE: ResourceStore | None = None


def initialize_store(config: ServerConfig) -> ResourceStore:
    global _STORE
    RdfDataSet.configure("Oxigraph", [config.store.path])
    _STORE = RdfResourceStore(RdfDataSet.VALUE)
    return _STORE


def get_store():
    global _STORE
    if not _STORE:
        raise ServerException("Resource store not initialized", logging.CRITICAL)
    return _STORE
