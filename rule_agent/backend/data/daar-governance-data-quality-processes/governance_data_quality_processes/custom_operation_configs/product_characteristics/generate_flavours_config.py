from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class GenerateFlavoursConfig:
    """
    generate flavours based on n-grams (if n != 0) or words (if n == 0). flavours taken from reference 'other' dataframe 
    """
    
    max_rank_to_vote: int
    """ maximal rank of record to be taken into account while voting for flavour """

    other: str
    """ reference dataframe context name to look into for flavors """

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
    """ sizes of n-grams on which flavours will be matched """

    join_hierarchy_list: List[List[str]]
    """ list of lists of columns to join on. Each list represents a level of the hierarchy. ex [[column_map['brand_name'], column_map['sub_brand_name'], column_map['country_code']], [column_map['brand_name'], column_map['sub_brand_name']], []] """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class GenerateFlavoursOperationConfig(CommonConfig):

    params: GenerateFlavoursConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
