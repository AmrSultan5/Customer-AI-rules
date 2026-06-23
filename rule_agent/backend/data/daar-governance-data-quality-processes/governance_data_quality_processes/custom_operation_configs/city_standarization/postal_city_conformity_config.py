from marshmallow_dataclass import dataclass
from typing import ClassVar, Type, Optional
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig


@dataclass
class PostalCityConformityConfig:
    """
    set of fields for the check
    """

    customer_code: str
    """ input column with customer_code """

    country_code: str
    """ input column with country_code """

    value_checked: str
    """ input column with value_checked """

    enriched_value: str
    """ input column with enriched_value """

    valid_country: str
    """ input column with valid_country """

    valid_city: str
    """ input column with valid_city """

    check_dict_city: str
    """ input column with check_dict_city """

    location_info: str
    """ input column with location_info """

    location_info_ext: str
    """ input column with location_info_ext """

    location_info_ext2: str
    """ input column with location_info_ext2 """

    city: str
    """ input column with city """

    context_name: Optional[str] = None

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class PostalCityConformityOperationConfig(CommonConfig):
    """
    Operation configuration for PostalCityConformityOperation
    """

    params: PostalCityConformityConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
