from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig


@dataclass
class CaseWhenConfig:
    """
    Case When dataframe
    """

    column: str
    """ string condition """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class CaseWhenOperationConfig(CommonConfig):
    """
    Operation configuration for case when dataframe data
    """

    params: CaseWhenConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
