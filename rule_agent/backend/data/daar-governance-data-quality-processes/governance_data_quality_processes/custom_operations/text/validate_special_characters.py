from pyspark.sql.dataframe import DataFrame
from pyspark.sql.functions import col, pandas_udf
from pyspark.sql.types import IntegerType
from typing import Optional
import pandas as pd
import re

from datamesh_common.utils.base_utils import log_execution_time
from datamesh_transformation.operations.base import BaseOperation
from datamesh_transformation.common.context import TransformationContext
from governance_data_quality_processes.custom_operation_configs.text.validate_special_characters_config import (
    ValidateSpecialCharactersOperationConfig,
)

class ValidateSpecialCharactersOperation(BaseOperation):
    @log_execution_time
    def transform(self, ctx: TransformationContext) -> Optional[DataFrame]:
        assert isinstance(self._config, ValidateSpecialCharactersOperationConfig)
        df = ctx[self._config.context_name]
        column_to_validate = self._config.params.value
        country_column = self._config.params.country_code

        allowed_base_chars = (
            "éÈÉèA-Za-z0-9'()\\-./*@{}\\[\\]%<>,'^|/"
            + "\u0370-\u03FF"   # Greek and Coptic block — keep
            + "\u1F00-\u1FFF"   # Greek Extended block — keep
            + "\u200B"          # ZWSP
            + "\uFEFF"          # BOM
            + "\u00A0"          # NBSP
            + "\n\r "           # whitespace
        )
        allowed_base_strings = {"**", "***", "****", "*****", "||", "//",}
        consecutive_special_chars = r"'()\-*@{}\[\]%<>,^:;_!#"
        paired_chars = {"[]", "{}", "()", "\"\"", "«»"} #for curly quotes see additonal smart quote logic in main function

        country_rules = {
            "Rule_1": {"countries": {"NG", "GB", "IE"}, "chars": r":\&\""},
            "Rule_2": {"countries": {"GR", "CY"}, "chars": r"Α-Ωα-ωΆΈΉΊΌΎΏΪΫ'–\-&\.,;:!?_`\""},
            "Rule_3": {"countries": {"HU"}, "chars": r"áÁéÉíÍóÓöÖőŐüÜűŰÚúäÄ_!\#\*\&\"\+"},
            "Rule_4": {"countries": {"CH"}, "chars": r"ßäöüÄÖÜéàèùçâêîôûëïüÔÒÉÈÊÎÀÂÎČÏóÇÙÌÈÓ«»–‘!\+\&\"ÁòñÛáãÑĆŠÃíūŒŚÍžúáì​ËšÚ"},
            "Rule_5": {"countries": {"IT"}, "chars": r"éÉÈèàÀÁáÌìÍíÙùÚúÒòÓó_\&\""},
            "Rule_6": {"countries": {"SI", "HR", "BA"}, "chars": r":;?!Ċ–_ČĆŽŠĐčćžšđÖöÜüÐđŻżĆćČčŠšшШЂђЧчЋћљЉњЊжЖџЏ“”‘\&\"\+\€ЕАСМКЈЛ#ОВНИРÁФПБГДЗТУХЦабвгдезијклмнопрстуфхц"},
            "Rule_7": {"countries": {"KV"}, "chars": r"ČĆŽŠĐÇçËë“”‘\&\"ć\+Ü€О`ÐВȘМ\?Ė\$\…"},
            "Rule_8": {"countries": {"AT"}, "chars": r"ÄÖÜßäöü:;_\+!#\&\""},
            "Rule_9": {"countries": {"BG"}, "chars": r"А-я"},
            "Rule_10": {"countries": {"SK", "CZ"}, "chars": r"ěščřžýáíéĚŠČŘŽÝÁÍÉöÖúÚůŮóÓďĎťŤäÄľĽĺĹŕŔôÔňŇ!ʼ\+\&\":ăĐü´â–Ă”Ü“#çãćşÂÀśÕŚêòŞĒàłű~ńộ?ÌÇûđệŃĀÊęÅőøØ°"},
            "Rule_11": {"countries": {"AM"}, "chars": r"Ա-և«»-№_\&\"\+"},
            "Rule_12": {"countries": {"UA"}, "chars": r"А-ЯЄІЇҐа-яєіїґ№!\&\"\+:"},
            "Rule_13": {"countries": {"EG"}, "chars": r"ء-يآأإئة-ۿًا-ي-ْ؟؛،ـﺀ-ﻼ\&\""},
            "Rule_14": {"countries": {"PL"}, "chars": r"ąĄćĆęĘłŁńŃóÓśŚźŹżŻŞşŽžÄäÑñÖöÇçÁáČčŠšųĞğÜü&\":;!+_–=>‚˝´¨""„~"},
            "Rule_15": {"countries": {"EE"}, "chars": r"õÕäÄöÖüÜšŠžŽ&\"!̈“_̃”"},
            "Rule_16": {"countries": {"LT"}, "chars": r"čČšŠžŽąĄęĘėĖįĮųŲūŪ&\"”“"},
            "Rule_17": {"countries": {"LV"}, "chars": r"āĀēĒīĪūŪčČģĢķĶļĻņŅšŠžŽ&\"!_–“”„‘"},
            "Rule_18": {"countries": {"MK"}, "chars": r"А-яЃѓЅѕЉљЊњЌќЏџ_!Ј#\&\"\+јŠ–"},
            "Rule_19": {"countries": {"MD", "RO"}, "chars": r"\+–\.ţŞşÎîÂâĂășȘțȚ№$\?\&\"-'"},
            "Rule_20": {"countries": {"ME", "RS"}, "chars": r":;!Ċ–_ČĆŽŠĐčćžšđÖöÜüÐđŻżĆćČčŠšшШЂђЧчЋћљЉњЊжЖџЏ“”‘\&\"+\€ЕАСМКЈЛ#ОВНИРÁФПБГДЗТУХЦабвгдезијклмнопрстуфхц\$\?\…"},
        }

        def validate_string(value: Optional[str], country_code: Optional[str]) -> int:
            if not value or not isinstance(value, str):
                return 0

            
            value = (
                value.replace("“", '"')
                     .replace("”", '"')
                     .replace("„", '"')
                     .replace("’", "'")
                     .replace("\u00A0", " ")  # NBSP → space
            )

            value_rstrip = value.rstrip()


            if value_rstrip in allowed_base_strings:
                return 1

            base_pattern = f"^[{allowed_base_chars}]*$"
            if re.fullmatch(base_pattern, value):
                return 1

            allowed_repeated_chars = {s[0] for s in allowed_base_strings}

            for rule, data in country_rules.items():
                if country_code in data["countries"]:
                    custom_pattern = f"^[{allowed_base_chars}{data['chars'] or ''}]*$"
                    if re.fullmatch(custom_pattern, value):
                        if len(value) != 40:
                            for pair in paired_chars:
                                if value.count(pair[0]) != value.count(pair[1]):
                                    return 0
                        if value.count('"') % 2 != 0 and country_code != 'UA':
                            return 0
                        # Smart quotes balance: openings (“ + „) must match closings (”)
                        open_smart_quotes = value.count("“") + value.count("„")
                        close_smart_quotes = value.count("”")
                        if open_smart_quotes != close_smart_quotes:
                            return 0
                        pattern_without_allowed = ''.join(
                            ch for ch in consecutive_special_chars if ch not in allowed_repeated_chars
                        )
                        if re.search(f"([{pattern_without_allowed}])\\1+", value):
                            return 0

                        return 1
            return 0

        @pandas_udf(returnType=IntegerType())
        def validate_udf(value_col: pd.Series, country_col: pd.Series) -> pd.Series:
            return value_col.combine(country_col, validate_string)

        return df.withColumn("validation_result", validate_udf(col(column_to_validate), col(country_column)))
