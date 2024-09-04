import typing
from dataclasses import dataclass

import dacite
import yaml

from firm_server.exceptions import ServerException


@dataclass
class FileStoreConfig:
    path: str
    remote_subdir: str = "remote"
    tenants_subdir: str = "tenants"
    private_subdir: str = "private"


@dataclass
class RdfStoreConfig:
    path: str


@dataclass
class StoreDriverConfigs:
    rdf: RdfStoreConfig | None = None
    filesystem: FileStoreConfig | None = None


@dataclass
class ServerConfig:
    tenants: list[str]
    store: StoreDriverConfigs


def load_config(config_in: typing.IO | str) -> ServerConfig:
    def _load(config_stream: typing.IO):
        try:
            config_data = yaml.safe_load(config_stream)
            return dacite.from_dict(data_class=ServerConfig, data=config_data)
        except dacite.exceptions.DaciteError as e:
            raise ServerException(f"Invalid configuration: {e}")

    if isinstance(config_in, str):
        with open(config_in) as f:
            return _load(f)
    else:
        return _load(config_in)
