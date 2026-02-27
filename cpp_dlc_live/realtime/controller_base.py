from __future__ import annotations

from abc import ABC, abstractmethod


class LaserControllerBase(ABC):
    def __init__(self) -> None:
        self.current_state: bool = False

    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_state(self, on: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError
