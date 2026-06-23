from marshmallow_dataclass import dataclass
from typing import List, Dict, Optional
from typing import ClassVar, Type
from marshmallow import Schema  # noqa
from dataclasses import field

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class JoinInboxConfig:
    """
    join 2 dataframes
    """

    other: str
    """ name of the other dataframe """

    how: str
    """ how to join (left, right, inner, ...) """

    columns: Dict[str, Optional[str]]
    """ key fields """

    hint: Optional[str]
    """ Join hint for other frame """

    eq_null_safe: bool = field(default=False)
    """ for join condition use .eqNullSafe instead of == """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa


@dataclass
class JoinInboxOperationConfig(CommonConfig):
    """
    Operation configuration for joining inbox data frames
    """

    params: List[JoinInboxConfig]

    hint: Optional[str]

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

