from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class CommonTokensIdentifyConfig:
    """
    
    """
    tokens_list_col: str
    """ column name for list of tokens """
    
    group_cols: List[str]
    """ list of columns for group by """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class CommonTokensIdentifyOperationConfig(CommonConfig):

    params: CommonTokensIdentifyConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
