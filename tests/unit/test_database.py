from __future__ import annotations

from unittest.mock import MagicMock

from personal_ai_os.core.config import Settings
from personal_ai_os.db.engine import create_engine_for_settings, ping_database


def test_database_ping_executes_select_one() -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.return_value = 1

    ping_database(engine)

    statement = connection.execute.call_args.args[0]
    assert str(statement) == "SELECT 1"
    connection.execute.return_value.scalar_one.assert_called_once_with()


def test_database_engine_hides_bound_parameters_in_errors() -> None:
    engine = create_engine_for_settings(Settings(environment="test"))
    try:
        assert engine.hide_parameters is True
    finally:
        engine.dispose()
