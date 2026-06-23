from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class BrandSimilarityUnorderedConfig:
    """
    compare brand unordered similarity
    """

    input_brand_1: str
    """ input column with brand 1 """

    input_brand_2: str
    """ input column with brand 2 """
    
    output_col_name: str
    """ output column name """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class BrandSimilarityUnorderedOperationConfig(CommonConfig):
    """
    Operation configuration for comparing brand unordered similarity
    """

    params: BrandSimilarityUnorderedConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
