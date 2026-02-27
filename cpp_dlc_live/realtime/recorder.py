from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, List


class CSVRecorder:
    def __init__(self, path: Path, fieldnames: Iterable[str], flush_every: int = 200):
        self.path = Path(path)
        self.fieldnames = list(fieldnames)
        self.flush_every = int(flush_every)
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.fieldnames)
        self._writer.writeheader()
        self._buffer: List[Dict[str, object]] = []

    def write_row(self, row: Dict[str, object]) -> None:
        self._buffer.append({k: row.get(k) for k in self.fieldnames})
        if len(self._buffer) >= self.flush_every:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        self._writer.writerows(self._buffer)
        self._buffer.clear()
        self._file.flush()

    def close(self) -> None:
        self.flush()
        self._file.close()
