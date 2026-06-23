from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class GeolocatorSearchConfig:
    """
    set of fields of the address
    """

    house_number: str
    """ input column with house number """

    street: str
    """ input column with street """

    city: str
    """ input column with city """

    postcode: str
    """ input column with postcode """

    country_code: str
    """ input column with country code """

    country_filter: str
    """ input parameter with country filter """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class GeolocatorSearchOperationConfig(CommonConfig):
    """
    Operation configuration to find the set of coordinates corresponding to an adress
    """

    params: GeolocatorSearchConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
