# Databricks notebook source
# MAGIC %pip install governance-data-quality-processes==0.1.319rc4 --extra-index-url=https://${FEED_TOKEN}@pkgs.dev.azure.com/CCHBC/f6799d46-e250-45e0-8475-5662f88b0a2d/_packaging/daar-governance-data-quality-processes/pypi/simple/ --force-reinstall

# COMMAND ----------

# MAGIC %md
# MAGIC #INIT

# COMMAND ----------

import os
import json
import uuid
import pkgutil
import concurrent
from pyspark.sql import functions as f
from datamesh_data_io import ActiveDirectoryApplicationConfiguration, ApplicationDataLakeObject, CuratedDataLakeObject, DataLakeLayer, DataMeshDataIO, StorageConfiguration, RefreshMode
from datamesh_common.exceptions import DataLakeObjectNotRegisteredError

# COMMAND ----------

# MAGIC %md
# MAGIC #SETUP

# COMMAND ----------

threadPoolSize = 4

# COMMAND ----------

additional_objects = """{
}"""

# COMMAND ----------

# MAGIC %md
# MAGIC #LOAD SCHEMA VERSIONS

# COMMAND ----------

schema_configuration = {",".join(sorted(k.strip().replace(" ", "").split(","))): v.strip() for k, v in json.loads(additional_objects).items()}

# COMMAND ----------

pkg_json_path = "/configs/schema_versions/dcc_schema_versions.json"
json_data = pkgutil.get_data("governance_data_quality_processes", pkg_json_path)
json_data_decoded = json_data.decode("utf-8")

# COMMAND ----------

schema_configuration_dcc = {",".join(sorted(k.strip().replace(" ", "").split(","))): v.strip() for k, v in json.loads(json_data_decoded).items() if "layer:application" in k.strip().replace(" ", "")}
schema_configuration.update(schema_configuration_dcc)

# COMMAND ----------

# MAGIC %md
# MAGIC #INITIALIZE LAYERS

# COMMAND ----------

dataio_qlty_layer_curated = DataMeshDataIO(
    spark_session=spark,
    storage=StorageConfiguration.load(configuration_id=os.getenv("DATA_IO_STORAGE_ID")),
    active_directory_application_configuration=ActiveDirectoryApplicationConfiguration.load(
        configuration_id=os.getenv("DATA_IO_AD_ID")
    ),
    layer=DataLakeLayer.CURATED,
)

dataio_prod_layer_curated = DataMeshDataIO(
    spark_session=spark,
    storage=StorageConfiguration.load(configuration_id=os.getenv("DATA_IO_PROD_STORAGE_ID")),
    active_directory_application_configuration=ActiveDirectoryApplicationConfiguration.load(
        configuration_id=os.getenv("DATA_IO_AD_ID")
    ),
    layer=DataLakeLayer.CURATED,
)

# COMMAND ----------

dataio_qlty_layer_application = DataMeshDataIO(
    spark_session=spark,
    storage=StorageConfiguration.load(configuration_id=os.getenv("DATA_IO_STORAGE_ID")),
    active_directory_application_configuration=ActiveDirectoryApplicationConfiguration.load(
        configuration_id=os.getenv("DATA_IO_AD_ID")
    ),
    layer=DataLakeLayer.APPLICATION,
)

dataio_prod_layer_application = DataMeshDataIO(
    spark_session=spark,
    storage=StorageConfiguration.load(configuration_id=os.getenv("DATA_IO_PROD_STORAGE_ID")),
    active_directory_application_configuration=ActiveDirectoryApplicationConfiguration.load(
        configuration_id=os.getenv("DATA_IO_AD_ID")
    ),
    layer=DataLakeLayer.APPLICATION,
)

# COMMAND ----------

# MAGIC %md
# MAGIC #DEFINE TRANSFER FUNCTION

# COMMAND ----------

def transfer_objects(thread_schema_configurations: dict):
    for dataio_object, schema_version in thread_schema_configurations.items():
        dataio_object = dataio_object.replace(" ", "")
        dataio_object = {object_param.split(":")[0]: object_param.split(":")[1] for object_param in dataio_object.split(",")}
        dataio_object["schema_version"] = schema_version
        if dataio_object["layer"] == "application":
            data_lake_obj = ApplicationDataLakeObject(
                application_name=dataio_object["application_name"],
                country=dataio_object["country"],
                module=dataio_object["module"],
                namespace=dataio_object["namespace"],
                object_name=dataio_object["object_name"],
                schema_version=dataio_object["schema_version"],
            )
            repository_prod = dataio_prod_layer_application.repository(data_lake_object=data_lake_obj)
            repository_qlty = dataio_qlty_layer_application.repository(data_lake_object=data_lake_obj)
        elif dataio_object["layer"] == "curated":
            data_lake_obj = CuratedDataLakeObject(
                source=dataio_object["source"],
                namespace=dataio_object["namespace"],
                object_name=dataio_object["object_name"],
                schema_version=dataio_object["schema_version"],
            )
            repository_prod = dataio_prod_layer_curated.repository(data_lake_object=data_lake_obj)
            repository_qlty = dataio_qlty_layer_curated.repository(data_lake_object=data_lake_obj)
        try:
            df_prod_input = repository_prod.read()
        except DataLakeObjectNotRegisteredError:
            continue
        if repository_qlty.is_object_registered is False:
            repository_qlty.register_object()
        
        df_qa_input = repository_qlty.read()
        null_fill_value = str(uuid.uuid4())
        columns_list = sorted(df_prod_input.drop("process_run_id").columns)

        df_prod_pids = df_prod_input.withColumns({col_name: f.col(col_name).cast("string") for col_name in columns_list}).fillna(null_fill_value)
        df_prod_pids = df_prod_pids.select(f.xxhash64(f.concat_ws(",", *columns_list)).alias("checksum_prod"), "process_run_id")
        df_prod_pids = df_prod_pids.groupBy("process_run_id").agg(f.avg("checksum_prod").cast("long").cast("string").alias("checksum_prod"))

        df_qlty_pids = df_qa_input.withColumns({col_name: f.col(col_name).cast("string") for col_name in columns_list}).fillna(null_fill_value)
        df_qlty_pids = df_qlty_pids.select(f.xxhash64(f.concat_ws(",", *columns_list)).alias("checksum_qlty"), "process_run_id")
        df_qlty_pids = df_qlty_pids.groupBy("process_run_id").agg(f.avg("checksum_qlty").cast("long").cast("string").alias("checksum_qlty"))

        df_pids = df_prod_pids.join(df_qlty_pids, on="process_run_id", how="outer")
        df_pids = df_pids.filter(f.substring("checksum_prod", 0, 10) != f.substring("checksum_qlty", 0, 10)).cache()

        pids_new = [pid.process_run_id for pid in df_pids.filter(f.col("checksum_prod").isNotNull()).collect()]
        pids_to_be_deleted = [pid.process_run_id for pid in df_pids.filter(f.col("checksum_qlty").isNotNull()).collect()]
        df_pids.unpersist()

        if pids_to_be_deleted:
            repository_qlty.delete(f.col("process_run_id").isin(pids_to_be_deleted))
        for pid in pids_new:
            repository_qlty.write(df_prod_input.filter(f.col("process_run_id") == pid).drop("process_run_id"), refresh_mode=RefreshMode.append, process_run_id=pid)

# COMMAND ----------

# MAGIC %md
# MAGIC #EXECUTE TRANSFER

# COMMAND ----------

schema_version_splitted = [{} for i in range(threadPoolSize)]
i = 0
for schema_version_item in schema_configuration.items():
    schema_version_splitted[i%threadPoolSize][schema_version_item[0]] = schema_version_item[1]
    i = i + 1

thPoolExec = concurrent.futures.ThreadPoolExecutor(max_workers=threadPoolSize)

futures = [  thPoolExec.submit( transfer_objects, item ) for item in  schema_version_splitted ]

futureResults = []
for future in concurrent.futures.as_completed(futures):
    try:
        futureResult = future.result()
        futureResults.append( futureResult  )
    except Exception as exc:
        raise exc