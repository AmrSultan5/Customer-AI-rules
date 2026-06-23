from marshmallow_dataclass import dataclass
from typing import ClassVar, Type, Optional
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig


@dataclass
class AddressCoordsConformityConfig:
    """
    set of fields for the check
    """

    customer_code: str
    """ input column with customer_code """

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
    """ input column with citye """

    geocoords_extractor: str
    """ input column with country code """

    postal_check_status: str
    """ input column with country code """

    context_name: Optional[str] = None

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class AddressCoordsConformityOperationConfig(CommonConfig):
    """
    Operation configuration for AddressCoordsConformityOperation
    """

    params: AddressCoordsConformityConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
