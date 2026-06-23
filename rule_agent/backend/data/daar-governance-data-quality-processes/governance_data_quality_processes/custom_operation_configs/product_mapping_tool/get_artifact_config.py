from marshmallow_dataclass import dataclass
from typing import List
from typing import ClassVar, Type
from marshmallow import Schema  # noqa

from datamesh_transformation.operation_configs.common import CommonConfig
from datamesh_transformation.operation_configs.custom_config import CustomOperationConfig


@dataclass
class GetArtifactConfig:
    """
    get model artifact
    """

    catalog: str
    """ unity catalog """
    
    schema: str
    """ schema name """
    
    registered_model_name: str
    """ registered production model name """
    
    alias: str
    """ model alias """
    
    artifact_path: str
    """ inside-model artifact path """

    Schema: ClassVar[Type[Schema]] = Schema  # noqa

@dataclass
class GetArtifactOperationConfig(CommonConfig):

    params: GetArtifactConfig

    Schema: ClassVar[Type[Schema]] = Schema  # noqa
