from pyspark.sql import Row, Window
from pyspark.sql.functions import lit, col, current_timestamp, regexp_replace, udf, expr, concat, split, explode, array, row_number, avg, rank, collect_list, first, desc, max as spark_max, countDistinct, count, round, sum as spark_sum
from pyspark.sql.types import StringType, ArrayType, IntegerType, FloatType, StructType, StructField
from pyspark.ml.feature import StringIndexer
from typing import Optional
from pyspark.sql.dataframe import DataFrame
import re
import math

import nltk
from nltk import ngrams
from collections import Counter
import pandas as pd
from pyspark.sql.functions import pandas_udf

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext

from governance_data_quality_processes.custom_operation_configs.product_characteristics.generate_flavours_config import (
    GenerateFlavoursOperationConfig,
)

class GenerateFlavoursOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        """
        Generating columns flavour_name and flavour_probability based on words or tokens and reference table.
        """

        assert hasattr(self._config, 'params') and hasattr(self._config.params, 'column_map')
        column_map = self._config.params.column_map

        df = ctx[self._config.context_name]
        sap_mu = ctx[self._config.params.other]
        ll = self._config.params.max_rank_to_vote
        ngram_sizes = self._config.params.ngram_sizes
        join_hierarchy_list = self._config.params.join_hierarchy_list

        def lists_to_dict(keys, values):
            if len(keys) != len(values):
                raise ValueError("Both lists must have the same length")    
            return dict(zip(keys, values))
                
        # --- UDFs ---        
        def generate_tokens(text, n):
            if n != 0:
                text = re.sub(r'[^a-zA-Z0-9]', '', text)
                return [text[i:i+n] for i in range(len(text) - n + 1)]
            else:
                text = re.sub(r'[^a-zA-Z0-9 ]', ' ', text)
                return text.split()

        generate_tokens_udf = udf(generate_tokens, ArrayType(StringType()))

        def len_set_col(col_val):
            if col_val is not None:
                return len(set(col_val))
            return None

        len_set_col_udf = udf(len_set_col, IntegerType())

        def len_col(col_val):
            if col_val is not None:
                return len(col_val)
            return None

        len_col_udf = udf(len_col, IntegerType())

        def add_suffix_to_columns(suffix: str, df: DataFrame) -> DataFrame:
            new_column_names = [f"{c}{suffix}" for c in df.columns]
            return df.toDF(*new_column_names)

        def get_element_at_index(values, ll):
            if len(values) > ll:
                return values[ll]
            return values[len(values)-1]

        get_element_at_index_udf = udf(get_element_at_index, StringType())

        # vectorized weighted sum
        @pandas_udf(FloatType())
        def weighted_sum_pudf(values_series: pd.Series, weights_series: pd.Series) -> pd.Series:
            """
            Each element of values_series and weights_series is expected to be a Python list (or None).
            Returns a float per row = sum(v*w) over zipped lists. Returns None if input invalid.
            """
            def row_sum(vals, wts):
                if vals is None or wts is None:
                    return None
                try:
                    total = 0.0
                    for v, w in zip(vals, wts):
                        # safe conversion; skip invalid
                        try:
                            total += float(v) * float(w)
                        except Exception:
                            continue
                    return float(total)
                except Exception:
                    return None

            return values_series.combine(weights_series, lambda a, b: row_sum(a, b))

        def sort_by_length(list1, list2):
            if len(list1) != len(list2):
                raise ValueError("Lists must have the same length.")
            paired = list(zip(list1, list2))
            sorted_pairs = sorted(paired, key=lambda x: (len(x[0]), x[0]), reverse=True)
            sorted_list1, sorted_list2 = zip(*sorted_pairs)
            return list(sorted_list1), list(sorted_list2)

        # define return struct schema
        max_flavour_schema = StructType([
            StructField("flavour_name", StringType(), True),
            StructField("flavour_probability", FloatType(), True)
        ])

        @pandas_udf(max_flavour_schema)
        def max_flavour_pudf(*cols):
            """
            cols: first half = lists of flavours for each n, second half = lists of probabilities for each n
            Each pandas Series element is expected to be a Python list (or None).
            Returns a DataFrame-like result with two columns: flavour_name, flavour_probability.
            """
            # number of input Series
            num_series = len(cols)
            if num_series == 0:
                # return empty frame
                return pd.DataFrame({"flavour_name": [], "flavour_probability": []})

            # Convert tuple of Series into list for easier indexing
            series_list = list(cols)
            half = num_series // 2
            flav_series_list = series_list[:half]     # each is a pd.Series of lists (or None)
            prob_series_list = series_list[half:]     # each is a pd.Series of lists (or None)

            # We'll build result lists
            result_names = []
            result_probs = []

            # iterate over rows (vectorized function but we do per-row logic)
            length = len(series_list[0])
            for i in range(length):
                flav_row_lists = [s.iloc[i] for s in flav_series_list]
                prob_row_lists  = [s.iloc[i] for s in prob_series_list]

                pl_res = []
                fl_res = []
                # for each n-gram candidate (the original logic)
                for fl_list, pr_list in zip(flav_row_lists, prob_row_lists):
                    if pr_list is None or fl_list is None:
                        continue
                    # ensure both lists are actual lists
                    try:
                        # sort by flavour string length then lexicographically, descending (as your original)
                        paired = list(zip(fl_list, pr_list))
                        paired_sorted = sorted(paired, key=lambda x: (len(x[0]) if x[0] is not None else 0, x[0] if x[0] is not None else ""), reverse=True)
                        fl_sorted, pr_sorted = zip(*paired_sorted) if paired_sorted else ([], [])
                        # choose the candidate with the max probability among the sorted list
                        # convert pr_sorted to floats safely
                        pr_sorted_nums = []
                        for p in pr_sorted:
                            try:
                                pr_sorted_nums.append(float(p))
                            except Exception:
                                pr_sorted_nums.append(float("-inf"))
                        if pr_sorted_nums:
                            max_idx = int(pd.Series(pr_sorted_nums).idxmax())  # index in tuple
                            pl_res.append(pr_sorted_nums[max_idx])
                            fl_res.append(fl_sorted[max_idx])
                    except Exception:
                        continue

                if not pl_res:
                    # no candidate found
                    result_names.append(None)
                    result_probs.append(None)
                else:
                    # pick the flavour corresponding to the overall max probability
                    try:
                        overall_max_idx = int(pd.Series(pl_res).idxmax())
                        result_names.append(fl_res[overall_max_idx])
                        result_probs.append(float(pl_res[overall_max_idx]))
                    except Exception:
                        # fallback
                        result_names.append(None)
                        result_probs.append(None)

            # return DataFrame matching the schema
            return pd.DataFrame({"flavour_name": result_names, "flavour_probability": result_probs})
        
        # helper functions 
        def generate_flavours_sap(df: DataFrame, columns: list, n: int) -> DataFrame:
            print('generate_flavours_sap')
            print(columns)
            product_col = column_map['product_name'] + '_sap'
            flavour_col = column_map['flavour_name'] + '_sap'
            alias_flav_n, alias_count_n, alias_freq_n = f'flavours_list_{n}', f'flavours_count_{n}', f'flavours_freq_{n}'

            sap_fv = df.groupBy(columns + [product_col, flavour_col]).count().orderBy('count', ascending=False)
            window_spec = Window.partitionBy(columns).orderBy(col('count').desc())
            sap_fv = sap_fv.withColumn('rank_count', rank().over(window_spec))

            sap_fv_rank = sap_fv.groupBy(columns).agg(get_element_at_index_udf(collect_list("rank_count"), lit(ll-1)).alias("rank_limit"))
            sap_fv_rank = add_suffix_to_columns('_fv', sap_fv_rank)

            columns_to_drop = [c+"_fv" for c in columns]
            join_condition = expr(' AND '.join([f"df1.{c} = df2.{c}_fv" for c in columns]))

            sap_fv = sap_fv.alias("df1").join(sap_fv_rank.alias("df2"), on=join_condition, how='left') \
                .withColumn('w_rank', 1/(col('rank_count')*col('rank_count'))) \
                .drop(*columns_to_drop)

            sap_fv = sap_fv.filter(col('rank_count') <= col('rank_limit_fv')).drop('rank_count','rank_limit_fv')
            sap_fv = sap_fv.groupBy(columns + [flavour_col]).agg(weighted_sum_pudf(collect_list("count"), collect_list("w_rank")).alias("w_sum"))

            sap_fv_total_counts = sap_fv.groupBy(columns).agg(spark_sum('w_sum').alias('sum_total'))#.withColumnRenamed('sum(w_sum)','sum_total')
            sap_fv_total_counts = add_suffix_to_columns('_fv', sap_fv_total_counts)

            sap_fv = sap_fv.alias("df1").join(sap_fv_total_counts.alias("df2"), on=join_condition, how='left')
            sap_fv = sap_fv.withColumn('count_freq', col('w_sum')/col('sum_total_fv')).drop(*columns_to_drop).drop('sum_total_fv')

            sap_fv = sap_fv.groupBy(columns).agg(
                collect_list(flavour_col).alias(alias_flav_n),
                collect_list("w_sum").alias(alias_count_n),
                collect_list("count_freq").alias(alias_freq_n)
            )
            sap_fv = sap_fv.withColumnsRenamed(lists_to_dict(columns, columns_to_drop))

            return sap_fv

        def generate_flavours(df: DataFrame, no_flav: DataFrame, sap_df: DataFrame, columns: list, n: int) -> DataFrame:
            print('generate_flavours')
            print(columns)
            id_col = column_map['id']
            product_col = column_map['product_name']

            join_columns_sap = [f"df1.{c} = df2.{c}_sap" for c in columns]
            join_columns_sap.append('df1.tokens = df2.word_sap')
            join_condition_sap = expr(' AND '.join(join_columns_sap))

            join_columns_fv = [f"df1.{c} = df2.{c}_fv" for c in columns]
            join_columns_fv.append(f'df1.{product_col} = df2.{product_col}_fv')
            join_condition_fv = expr(' AND '.join(join_columns_fv))

            no_flav_tokens = df.filter(col(id_col).isin(no_flav.select(id_col).rdd.flatMap(lambda x:x).collect()))
            no_flav_tokens = no_flav_tokens.alias("df1").join(sap_df.alias("df2"), on=join_condition_sap, how='inner')

            sap_fv = generate_flavours_sap(no_flav_tokens, columns + [product_col], n)
            print(sap_fv.columns)

            columns_to_drop = [c+"_fv" for c in columns+[product_col]]
            result = no_flav.alias("df1").join(sap_fv.alias("df2"), on=join_condition_fv, how='left').drop(*columns_to_drop)

            return result

        # --- Processing of n-grams ---
        def process_flavours(n):
            id_col = column_map['id']
            product_col = column_map['product_name']
            flavour_col = column_map['flavour_name']
            brand_col = column_map['brand_name']
            sub_brand_col = column_map['sub_brand_name']
            country_col = column_map['country_code']

            # prepare SAP data and flavours
            sap_exp = sap_mu.select(product_col, brand_col, sub_brand_col, flavour_col, country_col).distinct() \
                            .withColumn('product_name_ngrams', generate_tokens_udf(col(product_col), lit(n))) \
                            .withColumn("word", explode(col('product_name_ngrams')))
            sap_exp = add_suffix_to_columns('_sap', sap_exp)

            flavours = sap_mu.select(brand_col, sub_brand_col, country_col, flavour_col).distinct() \
                                .withColumn('flavour_name_ngrams', generate_tokens_udf(col(flavour_col), lit(n))) \
                                .withColumn("word", explode(col('flavour_name_ngrams')))
            flavours = add_suffix_to_columns('_fv', flavours)

            df_exploded = df.withColumn('tokens', explode(generate_tokens_udf(col(product_col), lit(n)))).distinct()

            joined_df = df_exploded.join(
                flavours,
                (df_exploded[brand_col] == flavours[f'{brand_col}_fv']) &
                (df_exploded[sub_brand_col] == flavours[f'{sub_brand_col}_fv']) &
                (df_exploded[country_col] == flavours[f'{country_col}_fv']) &
                (df_exploded['tokens'] == flavours['word_fv']),
                'inner'
            )

            # aggregate tokens' frequency
            alias_flav_n, alias_count_n, alias_freq_n = f'flavours_list_{n}', f'flavours_count_{n}', f'flavours_freq_{n}'

            flavour_freq = (joined_df.groupBy(id_col, brand_col, sub_brand_col, country_col, f'{flavour_col}_fv')
                                    .agg(count('*').alias('count'),
                                        first(len_col_udf(col('flavour_name_ngrams_fv'))).alias('flavour_length'),
                                        collect_list("tokens").alias('tokens_list'))
                                    .withColumn('count_freq', col('count')/col('flavour_length'))
                                    .withColumn('tokens_list_len', len_set_col_udf(col('tokens_list')))
                                    .orderBy(col('count').desc(), col('count_freq').desc()))
            flavour_freq = flavour_freq.withColumn('test', col('tokens_list_len') * col('count_freq'))

            flavour_freq_max = flavour_freq.groupBy(id_col).agg(spark_max('test').alias('max_freq'))
            flavour_freq_max = flavour_freq_max.withColumnRenamed(id_col,'id_fv')
            flavour_freq = flavour_freq.join(flavour_freq_max, (flavour_freq[id_col]==flavour_freq_max['id_fv']), how='left').drop('id_fv')
            flavour_freq = flavour_freq.filter((col('count_freq')==col('max_freq')) & (col('tokens_list_len')==col('flavour_length')))

            flavour_freq = (flavour_freq.groupBy(id_col, brand_col, sub_brand_col, country_col)
                                    .agg(collect_list(f'{flavour_col}_fv').alias(alias_flav_n),
                                        collect_list("count").alias(alias_count_n),
                                        collect_list("count_freq").alias(alias_freq_n)))
        
            # Join with df
            ered_stage1 = df.join(
                flavour_freq,
                on=[id_col, brand_col, sub_brand_col, country_col],
                how='left'
            )

            # generate flavours for records with no flavours found yet
            no_flav = ered_stage1.filter(col(alias_flav_n).isNull()).drop(alias_flav_n, alias_count_n, alias_freq_n)
            flav = ered_stage1.filter(col(alias_flav_n).isNotNull())
            result = flav

            for stage in range(1,len(join_hierarchy_list)):
                if no_flav.count()>0:
                    column_list = join_hierarchy_list[stage-1]
                    res = generate_flavours(df_exploded, no_flav, sap_exp, column_list, n)
                    no_flav = res.filter(col(alias_flav_n).isNull()).drop(alias_flav_n, alias_count_n, alias_freq_n)
                    flav = res.filter(col(alias_flav_n).isNotNull())
                    result = result.union(flav)
                else:
                    break
            
            return result

        # --- main loop for n-grams ---
        result_dict = {}
        for n in ngram_sizes:
            print(f'Processing n={n}')
            result_dict[n] = process_flavours(n)

        # merge results into one dataframe
        merged_df = df
        id_col = column_map['id']
        for n in ngram_sizes:
            merged_df = merged_df.join(
                result_dict[n].select(id_col,
                                        f'flavours_list_{n}',
                                        f'flavours_freq_{n}'),
                on=id_col, how='left'
            )

        # max flavour final choice
        pudf_args = [col(f'flavours_list_{n}') for n in ngram_sizes] + [col(f'flavours_freq_{n}') for n in ngram_sizes]

        merged_df = merged_df.withColumn(
            'fv',
            max_flavour_pudf(*pudf_args)
        ).withColumn('flavour_name', col('fv').getItem('flavour_name')) \
            .withColumn('flavour_probability', col('fv').getItem('flavour_probability').cast('float')) \
            .drop('fv')

        drop_cols = []
        for n in ngram_sizes:
            drop_cols += [f'flavours_list_{n}', f'flavours_freq_{n}']
        drop_cols.append(column_map['brand_name'])
        merged_df = merged_df.drop(*drop_cols).orderBy(column_map['id'])

        return merged_df