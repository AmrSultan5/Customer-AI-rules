from pyspark.sql import Row, Window
from pyspark.sql.functions import lit, col, current_timestamp, regexp_replace, udf, expr, concat, split, explode, array, row_number, avg, rank, collect_list, first, desc, max as spark_max, countDistinct, count, round
from pyspark.sql.types import StringType, ArrayType, IntegerType, FloatType, StructType, StructField
from pyspark.ml.feature import StringIndexer
from typing import Optional
from pyspark.sql.dataframe import DataFrame
import re
import math

import nltk
from nltk import ngrams
from collections import Counter

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_mapping_ered.ered_flavours_config import (
    EredGenerateFlavoursOperationConfig,
)

class EredGenerateFlavoursOperation(BaseOperation):
    """Identifies flavour names for ERED products by matching word and character n-gram tokens against a SAP reference table, using weighted rank voting to select the best candidate."""

    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, EredGenerateFlavoursOperationConfig)
        df = ctx[self._config.context_name]
        description = self._config.params.description
        sap_mu = ctx[self._config.params.other]
        ll =  self._config.params.max_rank_to_vote

        def lists_to_dict(keys, values):
            if len(keys) != len(values):
                raise ValueError("Both lists must have the same length")    
            return dict(zip(keys, values))

        def generate_tokens(text, n):
            if n != 0:
                # generate character based ngrams
                text = re.sub(r'[^a-zA-Z0-9]', '', text)
                return [text[i:i+n] for i in range(len(text) - n + 1)]
            if n == 0:
                # tokens = words
                text = re.sub(r'[^a-zA-Z0-9 ]', ' ', text)
                return text.split()

        generate_tokens_udf = udf(generate_tokens,  ArrayType(StringType()))

        def len_set_col(col):
            if col != None:
                return len(set(col))
            else:
                return None

        len_set_col_udf = udf(len_set_col, IntegerType())

        def len_col(col):
            if col != None:
                return len(col)
            else:
                return None

        len_col_udf = udf(len_col, IntegerType())

        # adding suffix to column names
        def add_suffix_to_columns(suffix: str, df: DataFrame) -> DataFrame:
            new_column_names = [f"{col}{suffix}" for col in df.columns]    
            renamed_df = df.toDF(*new_column_names)    
            return renamed_df

        # get element at index for aggregation
        def get_element_at_index(values, ll):
            if len(values) > ll:
                return values[ll]
            else:
                return values[len(values) - 1] 

        get_element_at_index_udf = udf(get_element_at_index, StringType())

        # weighted sum for aggregation
        def weighted_sum(values, weights):
            total = sum(v * w for v, w in zip(values, weights))
            return total

        weighted_sum_udf = udf(weighted_sum, FloatType())

        # Sorting lists according to length of strings in the first list
        def sort_by_length(list1, list2):
            if len(list1) != len(list2):
                raise ValueError("Lists must have the same length.")

            paired = list(zip(list1, list2))    
            sorted_pairs = sorted(paired, key=lambda x: (len(x[0]), x[0]), reverse=True)    
            sorted_list1, sorted_list2 = zip(*sorted_pairs)    
            return list(sorted_list1), list(sorted_list2)

        def max_flavour(*args):
            fl = args[:len(args) // 2]
            pl = args[len(args) // 2:]

            pl_res = []
            fl_res = []
            
            for i in range(len(pl)):
                # if len(pl[i]) != 0:
                if pl[i] != None:
                    ff, pp = sort_by_length(fl[i], pl[i])
                    max_i = pp.index(max(pp))
                    pl_res.append(pp[max_i]) 
                    fl_res.append(ff[max_i]) 
            
            if not pl_res:
                return ""
            
            max_index = pl_res.index(max(pl_res))
            return [fl_res[max_index], max(pl_res)]

        max_flavour_udf = udf(max_flavour, ArrayType(StringType()))

        def generate_flavours_sap(df: DataFrame, columns: list, n: int) -> DataFrame:
            alias_flav_n, alias_count_n, alias_freq_n = f'flavours_list_{n}', f'flavours_count_{n}', f'flavours_freq_{n}'
            sap_fv = df.groupBy(columns + ['product_name_cleansed_sap', 'flavour_name_cleansed_sap']).count().orderBy('count', ascending=False)

            window_spec = Window.partitionBy(columns).orderBy(col('count').desc())

            sap_fv = sap_fv.withColumn('rank_count', rank().over(window_spec))
            sap_fv_rank = sap_fv.groupBy(columns).agg(get_element_at_index_udf(collect_list("rank_count"), lit(ll - 1)).alias("rank_limit"))
            sap_fv_rank = add_suffix_to_columns('_fv', sap_fv_rank)

            columns_to_drop = [item + "_fv" for item in columns]
            join_condition = expr(' AND '.join([f"df1.{cc} = df2.{cc}_fv" for cc in columns]))

            sap_fv = sap_fv.alias("df1").join(sap_fv_rank.alias("df2"), on = join_condition, how = 'left') \
                        .withColumn('w_rank', 1/(col('rank_count')*col('rank_count'))) \
                        .drop(*columns_to_drop)

            sap_fv = sap_fv.filter(col('rank_count') <= col('rank_limit_fv')).drop('rank_count', 'rank_limit_fv')
            
            # 1/sqrt(rank) weighted voting
            sap_fv = sap_fv.groupBy(columns + ['flavour_name_cleansed_sap']).agg(weighted_sum_udf(collect_list("count"), collect_list("w_rank")).alias("w_sum"))
            sap_fv_total_counts = sap_fv.groupBy(columns).sum('w_sum').withColumnRenamed('sum(w_sum)', 'sum_total')
            sap_fv_total_counts = add_suffix_to_columns('_fv', sap_fv_total_counts)

            sap_fv = sap_fv.alias("df1").join(sap_fv_total_counts.alias("df2"), on = join_condition, how = 'left')
            sap_fv = sap_fv.withColumn('count_freq', col('w_sum')/col('sum_total_fv'))
            sap_fv = sap_fv.drop(*columns_to_drop).drop('sum_total_fv')
                                
            sap_fv = sap_fv.groupBy(columns) \
                    .agg(collect_list("flavour_name_cleansed_sap").alias(alias_flav_n), 
                        collect_list("w_sum").alias(alias_count_n), 
                        collect_list("count_freq").alias(alias_freq_n))
            sap_fv = sap_fv.withColumnsRenamed(lists_to_dict(columns, columns_to_drop))

            return sap_fv

        def generate_flavours(df: DataFrame, no_flav: DataFrame, sap_df:DataFrame, columns: list, n: int) -> DataFrame:

            join_columns_sap = [f"df1.{cc} = df2.{cc}_sap" for cc in columns]
            join_columns_sap.append('df1.tokens = df2.word_sap')
            join_condition_sap = expr(' AND '.join(join_columns_sap))

            join_columns_fv = [f"df1.{cc} = df2.{cc}_fv" for cc in columns]
            join_columns_fv.append('df1.product_name_cleansed = df2.product_name_cleansed_fv')
            join_condition_fv = expr(' AND '.join(join_columns_fv))

            no_flav_tokens = df.filter(col('id').isin(no_flav.select('id').rdd.flatMap(lambda x: x).collect()))
            no_flav_tokens = no_flav_tokens.alias("df1").join(sap_df.alias("df2"), on = join_condition_sap, how = 'inner')

            column_list = columns + ['product_name_cleansed']
            sap_fv = generate_flavours_sap(no_flav_tokens, column_list, n)

            # Join results back to ered_stage1_no_flav
            columns_to_drop = [item + "_fv" for item in column_list]
            result = no_flav.alias("df1").join(sap_fv.alias("df2"), on = join_condition_fv, how='left').drop(*columns_to_drop)

            return result        
        
        def process_flavours(n):
            sap_exp = sap_mu.select('product_name_cleansed', 'brand_name_cleansed', 'sub_brand_name', 'flavour_name_cleansed', 'country_code').distinct() \
                            .withColumn('product_name_ngrams', generate_tokens_udf(col('product_name_cleansed'), lit(n))) \
                            .withColumn("word", explode(col('product_name_ngrams')))
            sap_exp = add_suffix_to_columns('_sap', sap_exp)

            flavours = sap_mu.select('brand_name_cleansed', 'sub_brand_name', 'country_code', 'flavour_name_cleansed').distinct() \
                            .withColumn('flavour_name_ngrams', generate_tokens_udf(col('flavour_name_cleansed'), lit(n))) \
                            .withColumn("word", explode(col('flavour_name_ngrams')))
            flavours = add_suffix_to_columns('_fv', flavours)

            df_exploded = df.withColumn('tokens', explode(generate_tokens_udf(col('product_name_cleansed'), lit(n)))).distinct()

            # Join with flavours DataFrame
            joined_df = df_exploded.join(flavours, (df_exploded['brand_name_cleansed'] == flavours['brand_name_cleansed_fv']) & \
                                        (df_exploded['sub_brand_name'] == flavours['sub_brand_name_fv']) & \
                                        (df_exploded['country_code'] == flavours['country_code_fv']) & \
                                        (df_exploded['tokens'] == flavours['word_fv']), 'inner')

            flavour_freq = (joined_df.groupBy('id', 'brand_name_cleansed', 'sub_brand_name', 'country_code', 'flavour_name_cleansed_fv')
                                    .agg(count('*').alias('count'), 
                                        first('brand_name_cleansed').alias('brand_name_cleansed_fv'), 
                                        first('sub_brand_name').alias('sub_brand_name_fv'), 
                                        first(len_col_udf(col('flavour_name_ngrams_fv'))).alias('flavour_length'),
                                        collect_list("tokens").alias('tokens_list'))
                                    .withColumn('count_freq', col('count') / col('flavour_length')) \
                                    .withColumn('tokens_list_len', len_set_col_udf(col('tokens_list'))) \
                                    .orderBy(col('count').desc(), col('count_freq').desc()))
            flavour_freq_max = flavour_freq.groupBy('id').agg(spark_max('count_freq').alias('max_freq'))
            flavour_freq_max = flavour_freq_max.withColumnRenamed('id', 'id_fv')
            flavour_freq = flavour_freq.join(flavour_freq_max, (flavour_freq['id'] == flavour_freq_max['id_fv']), how = 'left').drop('id_fv')
            flavour_freq = flavour_freq.filter((col('count_freq') == col('max_freq')) & (col('tokens_list_len') == col('flavour_length')))

            alias_flav_n, alias_count_n, alias_freq_n = f'flavours_list_{n}', f'flavours_count_{n}', f'flavours_freq_{n}'

            flavour_freq = (flavour_freq.groupBy("id", 'brand_name_cleansed', 'sub_brand_name', 'country_code')
                                    .agg(collect_list("flavour_name_cleansed_fv").alias(alias_flav_n), 
                                            collect_list("count").alias(alias_count_n), 
                                            collect_list("count_freq").alias(alias_freq_n), 
                                            first('brand_name_cleansed').alias('brand_name_cleansed_fv'), 
                                            first('sub_brand_name').alias('sub_brand_name_fv'), 
                                            first('country_code').alias('country_code_fv')))
            flavour_freq = flavour_freq.withColumnRenamed('id', 'id_fv').drop('brand_name_cleansed', 'country_code', 'sub_brand_name')

            # Join results back to df
            ered_stage1 = (df.join(flavour_freq,
                                        on=(df['country_code'] == flavour_freq['country_code_fv']) & 
                                            (df['brand_name_cleansed'] == flavour_freq['brand_name_cleansed_fv']) & 
                                            (df['sub_brand_name'] == flavour_freq['sub_brand_name_fv']) & 
                                            (df['id'] == flavour_freq['id_fv']), 
                                        how='left')
                                .drop('brand_name_cleansed_fv', 'sub_brand_name_fv', 'country_code_fv', 'id_fv'))
            
            column_lists = [['brand_name_cleansed', 'sub_brand_name', 'country_code'],
                            ['brand_name_cleansed', 'sub_brand_name'],
                            []]
            
            no_flav = ered_stage1.filter(col(alias_flav_n).isNull()).drop(alias_flav_n, alias_count_n, alias_freq_n)
            flav = ered_stage1.filter(col(alias_flav_n).isNotNull())

            result = flav

            # Process stages
            for stage in range(1, len(column_lists)):
                if no_flav.count() > 0:
                    column_list = column_lists[stage - 1]

                    # Join results back
                    res = generate_flavours(df_exploded, no_flav, sap_exp, column_list, n)

                    no_flav = res.filter(col(alias_flav_n).isNull()).drop(alias_flav_n, alias_count_n, alias_freq_n)
                    flav = res.filter(col(alias_flav_n).isNotNull())

                    result = result.union(flav)             
                else:
                    break  # Exit if no new flavours are found
            return result
        
        for n in [0,5,4,3]:
            print(f'n = {str(n)}')
            result = process_flavours(n)

            if n == 0:
                result0 = result
            elif n == 3:
                result3 = result
            elif n == 4:
                result4 = result
            elif n == 5:
                result5 = result

        ered_flav = df.join(result0.select('id', 'flavours_list_0', 'flavours_freq_0'), on='id', how='left') \
                .join(result3.select('id', 'flavours_list_3', 'flavours_freq_3'), on='id', how='left') \
                .join(result4.select('id', 'flavours_list_4', 'flavours_freq_4'), on='id', how='left') \
                .join(result5.select('id', 'flavours_list_5', 'flavours_freq_5'), on='id', how='left')

        ered_flav = ered_flav.withColumn('fv', max_flavour_udf(col('flavours_list_0'), col('flavours_list_5'), col('flavours_list_4'), col('flavours_list_3'), col('flavours_freq_0'), col('flavours_freq_5'), col('flavours_freq_4'), col('flavours_freq_3'))) \
            .withColumn("flavour_name", col("fv").getItem(0)) \
                    .withColumn("flavour_probability", col("fv").getItem(1).cast('float')) \
                    .drop('fv')

        ered_flav = ered_flav.orderBy('id').drop('id', 'flavours_list_0','flavours_list_5','flavours_list_4','flavours_list_3','flavours_freq_0','flavours_freq_5','flavours_freq_4','flavours_freq_3','brand_name_cleansed')

        return ered_flav
