from marshmallow_dataclass import dataclass
from typing import ClassVar, Type, Optional
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig


@dataclass
class PostalCountryConformityConfig:
    """
    set of fields for the check
    """

    customer_code: str
    """ input column with customer_code """

    country_code: str
    """ input column with country_code """

    city : str
    """ input column with city """

    value_checked: str
    """ input column with value_checked """

    post_code: str
    """ input column with post_code """

    enriched_value: str
    """ input column with enriched_value """

    valid_country: str
    """ input column with valid_country """

    location_info: str
    """ input column with location_info """

    context_name: Optional[str] = None

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class PostalCountryConformityOperationConfig(CommonConfig):
    """
    Operation configuration for PostalCountryConformityOperation
    """

    params: PostalCountryConformityConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
