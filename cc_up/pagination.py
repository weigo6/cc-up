"""Cursor navigation stores only page boundaries, never previous page records."""
from dataclasses import dataclass, field
from urllib.parse import urlencode


@dataclass
class Pages:
    index: int = 0
    cursors: list[str | None] = field(default_factory=lambda: [None])
    next_cursor: str | None = None

    def path(self, endpoint: str, index: int) -> str:
        if index < 0 or index > self.index + 1:
            raise ValueError('分页位置无效。')
        cursor = self.next_cursor if index == self.index + 1 else self.cursors[index]
        if index > self.index and not cursor:
            raise ValueError('已到最后一页。')
        return endpoint + ('?' + urlencode({'cursor': cursor}) if cursor else '')

    def accept(self, index: int, result: dict) -> None:
        if index == len(self.cursors):
            self.cursors.append(self.next_cursor)
        self.index = index
        self.next_cursor = result.get('next_cursor') or None
        del self.cursors[index + 1:]
