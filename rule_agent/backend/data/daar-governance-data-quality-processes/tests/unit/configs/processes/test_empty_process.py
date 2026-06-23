import io
import pytest


class TestEmptyProcess:
    @pytest.mark.parametrize(
        "config_path",
        [("processes/empty_process.yaml")],
    )
    def test_empty_process(self, config_path: str):
        config_path = f"governance_data_quality_processes/configs/{config_path}"
        with io.open(config_path, mode="r") as fp:
            config = fp.read()
        assert config == "{{content}}"
