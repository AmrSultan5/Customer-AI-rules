from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class GetFromViesConfig:
    """
    vat number
    """

    vat: str
    """ input column with vat """

    country_code: str
    """ input column with country code """

    country_filter: str
    """ input parameter with country filter """ 

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class GetFromViesOperationConfig(CommonConfig):
    """
    Operation configuration to verify eu vat number
    """

    params: GetFromViesConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
