python -m flake8 --max-line-length 120 --max-complexity 10 --exclude \entrypoints .
python -m flake8 --max-line-length 120 --max-complexity 10 \tests

python -m black --line-length 120 --target-version py38 --check --diff --exclude \entrypoints .
python -m black --line-length 120 --target-version py38 --check --diff \tests

python -m pylint --disable=R,C,fixme --enable=inconsistent-return-statements --max-line-length=120 $(find . -type f -name "*.py" -not -path "./entrypoints/*") --msg-template="{path}:{line}: [{msg_id}({symbol}), {obj}] {msg}" |& tee ./pylint_report.txt ; ( exit ${PIPESTATUS} )
python -m pylint --disable=R,C,fixme --enable=inconsistent-return-statements --max-line-length=120 $(find \tests -type f -name "*.py") --msg-template="{path}:{line}: [{msg_id}({symbol}), {obj}] {msg}" |& tee ./pylint_report.txt ; ( exit ${PIPESTATUS} )

python -m mypy --ignore-missing-imports --junit-xml ./tests/reports/mypy_errors_junit.xml --exclude \entrypoints .
python -m mypy --ignore-missing-imports --junit-xml ./tests/reports/mypy_errors_junit.xml \tests
