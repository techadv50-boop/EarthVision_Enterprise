"""Qt compatibility helpers."""

import pytest

try:
    from webcrawler.qtcompat import QT_API, qt_exec
except ImportError:
    pytest.skip("Qt GUI libs not loadable in this environment", allow_module_level=True)


def test_qt_api_is_pyside6_or_pyside2():
    assert QT_API in {"PySide6", "PySide2"}


def test_qt_exec_callable_exists():
    assert callable(qt_exec)
