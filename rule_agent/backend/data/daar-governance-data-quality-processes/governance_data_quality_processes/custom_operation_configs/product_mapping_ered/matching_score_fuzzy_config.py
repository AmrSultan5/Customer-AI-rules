from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class MatchingScoreFuzzyConfig:
    """
    calculate text similarity score
    """

    input_desc_1: str
    """ input column with text """

    input_desc_2: str
    """ input column with text """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class MatchingScoreFuzzyOperationConfig(CommonConfig):
    """
    Operation configuration for calculating text similarity score
    """

    params: MatchingScoreFuzzyConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
