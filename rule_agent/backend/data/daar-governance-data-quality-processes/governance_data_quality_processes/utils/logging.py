from functools import wraps
from time import time
from datetime import timedelta

from pyspark.sql import DataFrame
from logging import LoggerAdapter

from datamesh_common.logging.custom_logger import CustomLogger

logger = CustomLogger.get_logger(logger_name="default", static_kwargs={"app": "governance.data_quality_processes"})


def log_time(logger: LoggerAdapter):  # pylint: disable=redefined-outer-name
    def decorator(func):
        @wraps(func)
        def wrap(*args, **kw):
            ts = time()
            logger.info(f"Starting: {func.__qualname__}...")
            result = func(*args, **kw)
            te = time()
            time_total = str(timedelta(seconds=te - ts))
            logger.info(f"Function {func.__qualname__} took: {time_total}")
            return result

        return wrap

    return decorator


def log_count(logger: LoggerAdapter):  # pylint: disable=redefined-outer-name
    def decorator(func):
        @wraps(func)
        def wrap(*args, **kwargs):
            result = func(*args, **kwargs)
            if isinstance(result, DataFrame):
                result = result.cache()
                logger.info(f"func {func.__qualname__} returned {result.count()} rows")
            return result

        return wrap

    return decorator
