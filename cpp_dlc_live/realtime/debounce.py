from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Debouncer:
    required_count: int
    initial_state: str = "unknown"

    def __post_init__(self) -> None:
        if self.required_count < 1:
            raise ValueError("required_count must be >= 1")
        self._stable_state = self.initial_state
        self._candidate_state = self.initial_state
        self._candidate_count = 0

    @property
    def stable_state(self) -> str:
        return self._stable_state

    def update(self, candidate_state: str) -> str:
        if self.required_count == 1:
            self._stable_state = candidate_state
            self._candidate_state = candidate_state
            self._candidate_count = 1
            return self._stable_state

        if candidate_state == self._stable_state:
            self._candidate_state = candidate_state
            self._candidate_count = 0
            return self._stable_state

        if candidate_state == self._candidate_state:
            self._candidate_count += 1
        else:
            self._candidate_state = candidate_state
            self._candidate_count = 1

        if self._candidate_count >= self.required_count:
            self._stable_state = self._candidate_state
            self._candidate_count = 0

        return self._stable_state
