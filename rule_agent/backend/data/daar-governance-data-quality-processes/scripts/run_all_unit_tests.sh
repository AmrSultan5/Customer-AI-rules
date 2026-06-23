#!/bin/sh
set -ex

PROJECT_ROOT_DIR="$(
  cd "$(dirname "$0")/.."
  pwd -P
)"

UNIT_TESTS_DIR=${PROJECT_ROOT_DIR}/tests/unit
TEST_REPORTS_DIR=${PROJECT_ROOT_DIR}/tests/reports

export PYTHONPATH=${PROJECT_ROOT_DIR}:${PYTHONPATH}

if [ -z "${JAVA_HOME}" ]; then
  export JAVA_HOME='/usr/bin/java'
fi

if [ -z "${SPARK_HOME}" ]; then
  export SPARK_HOME='./opt/spark/'
fi

if [ -z "${HADOOP_HOME}" ]; then
  export HADOOP_HOME='./opt/hadoop/'
fi

HADOOP_LIB_PATH=${HADOOP_HOME}/share/hadoop/
export SPARK_DIST_CLASSPATH=${HADOOP_LIB_PATH}common/lib/*:${HADOOP_LIB_PATH}common/*:${HADOOP_LIB_PATH}hdfs/*:${HADOOP_LIB_PATH}hdfs/lib/*:${HADOOP_LIB_PATH}mapreduce/*:${HADOOP_LIB_PATH}mapreduce/lib/*:${HADOOP_LIB_PATH}tools/lib/*
export EXECUTION_TIMES_LOG_ENABLED=True

echo '--- Script variables ---'
echo 'PROJECT_ROOT_DIR:' ${PROJECT_ROOT_DIR}
echo 'UNIT_TESTS_DIR:' ${UNIT_TESTS_DIR}
echo 'TEST_REPORTS_DIR:' ${TEST_REPORTS_DIR}
echo 'HADOOP_LIB_PATH:' ${HADOOP_LIB_PATH}
echo 'EXECUTION_TIMES_LOG_ENABLED:' ${EXECUTION_TIMES_LOG_ENABLED}

echo '--- Environment variables ---'
echo 'JAVA_HOME:' ${JAVA_HOME}
echo 'PYTHONPATH:' ${PYTHONPATH}
echo 'SPARK_HOME:' ${SPARK_HOME}
echo 'HADOOP_HOME:' ${HADOOP_HOME}
echo 'SPARK_DIST_CLASSPATH:' ${SPARK_DIST_CLASSPATH}

cd ${PROJECT_ROOT_DIR}

python -m pytest \
  --numprocesses auto --dist=loadfile --max-worker-restart 0 \
  --durations=10 \
  --ignore=entrypoints \
  --doctest-modules \
  --cov=datamesh_data_io --cov-report=term --cov-report=xml:${TEST_REPORTS_DIR}/test_coverage.xml --cov-fail-under=80 \
  --html=${TEST_REPORTS_DIR}/test_summary.html --self-contained-html \
  --junitxml=${TEST_REPORTS_DIR}/test_summary_junit.xml -o junit_family=xunit2 \
  ${UNIT_TESTS_DIR}
