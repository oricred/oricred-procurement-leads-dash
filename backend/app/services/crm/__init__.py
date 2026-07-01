from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class CRMItem:
    id: str
    name: str
    column_values: dict[str, Any]


@dataclass
class Activity:
    event: str
    data: dict
    created_at: datetime


class CRMAdapter(ABC):

    @abstractmethod
    async def create_item(
        self, board_id: str, group_id: str, name: str, column_values: dict
    ) -> str: ...

    @abstractmethod
    async def update_column_value(
        self, item_id: str, column_id: str, value: Any
    ) -> None: ...

    @abstractmethod
    async def get_recent_activity(
        self, board_id: str, since: datetime
    ) -> list[Activity]: ...

    @abstractmethod
    async def search_items(self, board_id: str, term: str) -> list[CRMItem]: ...
