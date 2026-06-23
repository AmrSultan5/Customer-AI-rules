from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class HierarchicalJoinConfig:
    """
    Hierarchical JOIN with adjustable hierarchy.
    """

    join_cols: List[str]
    """ main columns list to join on """

    other: str
    """ reference dataframe context name to be joined """

    other_join_cols: List[str]
    """ columns list to join on in other dataframe """

    join_hierarchy_list: List[List[str]]
    """ list of lists of columns to join on. Each list represents a level of the hierarchy. ex. [['brand_name', 'sub_brand_name', 'country_code'], ['brand_name', 'sub_brand_name'], []] """

    how: str
    """ type of join"""

    id_col: str
    """ column with ids of context table to be used for joining """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class HierarchicalJoinOperationConfig(CommonConfig):

    params: HierarchicalJoinConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
