from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class GeolocatorReverseConfig:
    """
    set of coordinates
    """

    lat: str
    """ input column with latitude """

    lon: str
    """ input column with longitude """

    country_code: str
    """ input column with country code """

    country_filter: str
    """ input parameter with country filter """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class GeolocatorReverseOperationConfig(CommonConfig):
    """
    Operation configuration to find the address corresponding to a set of coordinates
    """

    params: GeolocatorReverseConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
