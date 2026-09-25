from typer.testing import CliRunner

from spliteasy import __version__
from spliteasy.cli.app import app

runner = CliRunner()


def test_version_prints_version_and_exits_successfully() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert f"SplitEasy {__version__}" in result.output
