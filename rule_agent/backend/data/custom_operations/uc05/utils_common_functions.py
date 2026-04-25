from pyspark.sql import functions as F

def util_repartition_dataframe(df, partition_columns, rows_threshold):
  
  stats_df = df.groupBy(partition_columns).agg(F.count(F.lit(1)).alias("_utils_cnt"))
  repartitioned_df = (
     df
    .join(stats_df, on = partition_columns)
    .withColumn("_utils_partition_seed"
                , ( F.rand() * stats_df["_utils_cnt"] / rows_threshold ).cast("int")
               )
    .repartition(*partition_columns, "_utils_partition_seed")
    .drop("_utils_partition_seed","_utils_cnt")
  )
  return repartitioned_df