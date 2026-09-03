"""Pytest fixtures wrap helpers so tests stay import-path independent."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from groktrading.models import Candidate, GateContext
from helpers import morning_pt, passing_candidate, passing_context


@pytest.fixture
def candidate_factory() -> Callable[..., Candidate]:
    return passing_candidate


@pytest.fixture
def context_factory() -> Callable[..., GateContext]:
    return passing_context


@pytest.fixture
def session_morning():
    return morning_pt()
