from marshmallow_dataclass import dataclass
from typing import ClassVar, Type, Optional
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig


@dataclass
class GeocoordsAddressConformityConfig:
    """
    set of fields for the check
    """

    customer_code: str
    """ input column with customer_code """

    central_order_block_code: str
    """ input column with central_order_block_code """

    latitude : str
    """ input column with latitude """

    longitude: str
    """ input column with longitude """

    post_code: str
    """ input column with post_code """

    street_house_number: str
    """ input column with street """

    country_code: str
    """ input column with country code """

    city: str
    """ input column with city """

    geocoords_extractor: str
    """ input column with geocoords_extractor """

    country_check_status: str
    """ input column with country_check_status """

    postal_check_status: str
    """ input column with postal_check_status """

    city_check_status: str
    """ input column with city_check_status """

    context_name: Optional[str] = None

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class GeocoordsAddressConformityOperationConfig(CommonConfig):
    """
    Operation configuration for GeocoordsAddressConformityOperation
    """

    params: GeocoordsAddressConformityConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
