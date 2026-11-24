"""Exercise collection and callback failures in disposable pytest processes."""
import json
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]
pytestmark = pytest.mark.qt


@pytest.fixture
def suite(pytester, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    pytester.makeconftest(Path(__file__).with_name("conftest.py").read_text(encoding="utf-8"))
    pytester.makeini("""[pytest]
addopts = --strict-markers
markers =
    logic: no application
    qt: offscreen compatible
    windows_native: Windows desktop
""")
    return pytester


def test_group_selection_follows_transitive_and_autouse_fixtures(suite):
    suite.makepyfile(test_mixed="""
import pytest
@pytest.fixture
def model(qapp): return object()
@pytest.fixture
def companion(native_desktop): raise AssertionError('must not execute during collection')
@pytest.fixture
def nested(companion): return companion
def test_rule(): pass
def test_model(model): pass
def test_hidden_native_dependency(nested): pass
""", test_autouse="""
import pytest
@pytest.fixture(autouse=True)
def readiness(native_desktop): pass
def test_apparently_pure(): pass
""")
    expected = {"logic": {"test_rule"}, "qt": {"test_model"},
                "windows_native": {"test_hidden_native_dependency", "test_apparently_pure"}}
    for group, names in expected.items():
        inventory = suite.path / f"{group}.json"
        result = suite.runpytest_subprocess("--collect-only", "-q", "-m", group,
                                           "--test-inventory", str(inventory))
        assert result.ret == 0
        records = json.loads(inventory.read_text())
        assert {r["nodeid"].split("::")[-1] for r in records} == names
        assert {r["group"] for r in records} == {group}


def test_native_selection_on_offscreen_is_an_error_before_test_body(suite):
    suite.makepyfile("""
import pytest
@pytest.mark.windows_native
def test_native(): raise AssertionError('body must not execute')
""")
    result = suite.runpytest_subprocess("-q", "-m", "windows_native")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "Native validation unavailable" in result.stderr.str()
    assert "body must not execute" not in result.stdout.str()


def test_logic_marker_cannot_hide_qt_fixture_dependency(suite):
    suite.makepyfile("""
import pytest
@pytest.mark.logic
def test_misclassified(qapp): pass
""")
    result = suite.runpytest_subprocess("--collect-only", "-q", "-m", "logic")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "understates fixture requirements" in result.stderr.str()


def test_real_qt_callback_exception_still_fails_run(suite):
    suite.makepyfile("""
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
def test_callback(qapp):
    def broken(): raise RuntimeError('callback-regression-sentinel')
    QTimer.singleShot(0, broken)
    QTest.qWait(20)
""")
    result = suite.runpytest_subprocess("-q", "-m", "qt")
    # PySide can propagate through qWait or route the exception to excepthook.
    # Both must fail the run; the next test independently guards our hook.
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    outcomes = result.parseoutcomes()
    assert outcomes.get("failed", 0) + outcomes.get("errors", 0) == 1
    assert "callback-regression-sentinel" in result.stdout.str()


def test_excepthook_errors_are_not_lost_at_teardown(suite):
    suite.makepyfile("""
import sys
def test_callback_hook(qapp):
    error = RuntimeError('excepthook-regression-sentinel')
    sys.excepthook(type(error), error, None)
""")
    result = suite.runpytest_subprocess("-q", "-m", "qt")
    result.assert_outcomes(passed=1, errors=1)
    assert "excepthook-regression-sentinel" in result.stdout.str()


def test_same_logic_regression_fails_full_and_reduced_selection(suite):
    suite.makepyfile("""
def test_rule():
    # Deliberately broken result: both routes must catch this regression.
    result = 3
    assert result == 2
def test_widget(qapp): pass
""")
    full = suite.runpytest_subprocess("-q")
    full.assert_outcomes(failed=1, passed=1)
    reduced = suite.runpytest_subprocess("-q", "-m", "logic")
    reduced.assert_outcomes(failed=1, deselected=1)
    assert "test_rule" in full.stdout.str() and "test_rule" in reduced.stdout.str()
