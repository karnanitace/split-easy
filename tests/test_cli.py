from spliteasy import __version__
from tests.conftest import invoke


def test_version_prints_version_and_exits_successfully() -> None:
    result = invoke(None, "version")

    assert result.exit_code == 0
    assert f"SplitEasy {__version__}" in result.output
