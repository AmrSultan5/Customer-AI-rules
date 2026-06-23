from marshmallow_dataclass import dataclass
from typing import ClassVar, Type, Optional
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig


@dataclass
class GeocoordsPostalConformityConfig:
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

    postal_code: str
    """ input column with post_code """

    country_code: str
    """ input column with country code """

    geocoords_extractor: str
    """ input column with geocoords_extractor """

    geocoords_extractor2: str
    """ input column with geocoords_extractor 2"""

    country_validation: str
    """ input column with country validation """

    city_validation: str
    """ input column with city validation """

    context_name: Optional[str] = None

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class GeocoordsPostalConformityOperationConfig(CommonConfig):
    """
    Operation configuration for GeocoordsPostalConformityOperation
    """

    params: GeocoordsPostalConformityConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
