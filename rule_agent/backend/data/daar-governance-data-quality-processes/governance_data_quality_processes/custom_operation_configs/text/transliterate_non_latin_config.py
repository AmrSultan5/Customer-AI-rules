from marshmallow_dataclass import dataclass
from typing import List, Dict, Optional
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class TransliterateNonLatinConfig:

    columns: Dict[str, Optional[str]]
    """ key fields """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class TransliterateNonLatinOperationConfig(CommonConfig):
    """
    Operation configuration to transliterate non latin characters
    """

    params: TransliterateNonLatinConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
