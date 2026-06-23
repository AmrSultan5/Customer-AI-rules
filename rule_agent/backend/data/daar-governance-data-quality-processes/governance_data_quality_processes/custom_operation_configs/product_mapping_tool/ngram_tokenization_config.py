from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class NgramTokenizationConfig:
    """
    
    """
    column_to_tokenize: str

    column_map: dict
    """ mapping of column names: 
        {
            'id': 'id',
            'product_name': 'product_name_cleansed',
            'brand_name': 'brand_name_cleansed',
            'sub_brand_name': 'sub_brand_name',
            'country_code': 'country_code',
            'flavour_name': 'flavour_name_cleansed'
        } 
    """

    ngram_sizes: List[int]
    """ sizes of n-grams on which flavours will be matched, n = 999 for words """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class NgramTokenizationOperationConfig(CommonConfig):

    params: NgramTokenizationConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
