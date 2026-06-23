from marshmallow_dataclass import dataclass
from typing import ClassVar, Type, Optional
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig


@dataclass
class CityStdConformityConfig:
    """
    set of fields for the check
    """

    value: str
    """ input column with value to check """

    latitude : str
    """ input column with latitude """

    longitude: str
    """ input column with longitude """

    country_code: str
    """ input column with country code """

    customer_code: str
    """ input column with customer_code """

    central_order_block_code: str
    """ input column with central_order_block_code """
    # Optional — only needed if you want to override context_name
    context_name: Optional[str] = None

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class CityStdConformityOperationConfig(CommonConfig):
    """
    Operation configuration for CityStdConformityOperation
    """

    params: CityStdConformityConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa