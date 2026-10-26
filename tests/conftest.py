"""Shared pytest fixtures + a zero-dependency async test runner.

pytest ships without native async support and requiring pytest-asyncio
would add a dependency just for the test harness, so ``pytest_pyfunc_call``
runs coroutine tests with :func:`asyncio.run` from the standard library.
Everything (library and tests) stays dependency-free.
"""
import asyncio
import inspect
import os
import sys

import pytest

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from patchswarm.bus import EventBus  # noqa: E402


def pytest_pyfunc_call(pyfuncitem):
    """Execute coroutine test functions on a fresh event loop."""
    testfunction = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunction):
        funcargs = pyfuncitem.funcargs
        argnames = pyfuncitem._fixtureinfo.argnames
        kwargs = {name: funcargs[name] for name in argnames}
        asyncio.run(testfunction(**kwargs))
        return True
    return False


REQUIREMENTS = """\
# demo service
requests==2.25.1
flask==2.0.1
django==4.1.0
jinja2==3.0.0
pyyaml>=4.0
sqlalchemy==2.0.20
"""


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def requirements():
    return REQUIREMENTS


@pytest.fixture
def clean_requirements():
    return "sqlalchemy==2.0.20\nrich==13.7.0\n"
