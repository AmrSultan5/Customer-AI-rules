from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class EredGenerateFlavoursConfig:
    """
    generate flavours based on n-grams (if n != 0) or words (if n == 0). flavours taken from reference 'other' dataframe 
    """

    description: str
    """ description column with text from which flavour will be generated """
    
    max_rank_to_vote: int
    """ maximal rank of record to be taken into account while voting for flavour """

    other: str
    """ reference dataframe context name to look into for flavors """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class EredGenerateFlavoursOperationConfig(CommonConfig):

    params: EredGenerateFlavoursConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
