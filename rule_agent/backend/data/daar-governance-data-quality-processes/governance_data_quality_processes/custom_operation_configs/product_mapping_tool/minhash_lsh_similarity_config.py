from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class MinHashLSHSimilarityConfig:
    """
    compare brand similarity with MinHash LSH
    """

    context_right: str
    """
    context name for right table data frame 
    """
    
    left_text_col: str
    """
    columns from left (context) table with texts to compare 
    """

    right_text_col: str
    """
    columns from right table with texts to compare 
    """

    output_prefix: str
    """
    prefix for output column
    """

    jaccard_threshold: float
    """
    threshold for jaccard similarity to be considered as match 
    """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class MinHashLSHSimilarityOperationConfig(CommonConfig):
    """
    Operation configuration for comparing brand similarity with MinHash LSH
    """

    params: MinHashLSHSimilarityConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
