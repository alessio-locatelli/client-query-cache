from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class BenchmarkError(Exception):
    pass


class BenchmarkConfigurationError(BenchmarkError, ValueError):
    pass


class ReportValidationError(BenchmarkError, ValueError):
    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))
