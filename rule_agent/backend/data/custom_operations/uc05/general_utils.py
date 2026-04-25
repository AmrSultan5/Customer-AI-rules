from pyspark.sql import functions as sf, DataFrame, SparkSession
from itertools import chain
from typing import List, Dict, AnyStr
import re
from pyspark.sql.types import DoubleType
from pyspark.sql.window import Window
from datamesh_data_io import (
    UdmDataLakeObject,
    ActiveDirectoryApplicationConfiguration,
    CuratedDataLakeObject,
    DataLakeLayer,
    DataMeshDataIO,
    StorageConfiguration,
    # MetadataDataLakeObject, #unused as of now, hence commented
)
import os

spark_var = SparkSession.builder.getOrCreate()


path = "/datamesh_data_io/configs/schema/curated/nielsen/cz/cz_sellout/v1"
splitted_path = path.split("/")
storage_id = os.getenv("DATA_IO_STORAGE_ID")
ad_id = os.getenv("DATA_IO_AD_ID")
synapse_id = os.getenv("DATA_IO_SYNAPSE_ID")


class GeneralUtils:
    """
    General utility class for the methods used across the project
    """

    @staticmethod
    def read_dataio_file(path: str, storage_id: str, ad_id: str, spark: SparkSession) -> DataFrame:
        """
        Function to read files from various layers of Data Mesh
        :param path: Path of the datamesh Object
        :param storage_id: Storage Configuration ID
        :param ad_id: Active Directory Configuration ID
        :param spark: Spark Session
        :return: The Spark Dataframe of the Datamesh file
        """
        splitted_path = path.split("/")
        print(storage_id)
        data_io = DataMeshDataIO(
            spark_session=spark,
            storage=StorageConfiguration.load(configuration_id=storage_id),
            layer=DataLakeLayer.CURATED,
            active_directory_application_configuration=ActiveDirectoryApplicationConfiguration.load(
                configuration_id=ad_id
            ),
        )

        curated_object = CuratedDataLakeObject(
            source=splitted_path[len(splitted_path) - 4],
            namespace=splitted_path[len(splitted_path) - 3],
            object_name=splitted_path[len(splitted_path) - 2],
            schema_version=splitted_path[len(splitted_path) - 1],
        )
        curated_repo = data_io.repository(curated_object)
        curated_df = curated_repo.read()

        return curated_df


# UDM
# data_io = DataMeshDataIO(
#             spark_session=spark,
#             storage=StorageConfiguration.load(configuration_id=storage_id),
#             layer=DataLakeLayer.UDM,
#             active_directory_application_configuration=ActiveDirectoryApplicationConfiguration.load(
#                 configuration_id=ad_id
#             ),
#         )

# udm_object = UdmDataLakeObject(
#     domain=splitted_path[len(splitted_path) - 4],  # paat
#     namespace=splitted_path[len(splitted_path) - 3],  # ca
#     object_name=splitted_path[len(splitted_path) - 2],  # universal_schema
#     schema_version=splitted_path[len(splitted_path) - 1],  # v1
#     )

# udm_repo = data_io.repository(udm_object)
# udm_df = udm_repo.read()
# udm_df.display()
