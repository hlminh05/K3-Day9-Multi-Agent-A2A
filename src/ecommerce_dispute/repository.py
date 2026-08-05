"""Read-only indexed access to the Olist CSV files used by the agents."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence


class OlistRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._orders = self._index_one("olist_orders_dataset.csv", "order_id")
        self._items = self._index_many("olist_order_items_dataset.csv", "order_id")
        self._payments = self._index_many("olist_order_payments_dataset.csv", "order_id")
        self._sellers = self._index_one("olist_sellers_dataset.csv", "seller_id")

    def _read(self, filename: str) -> list[dict[str, str]]:
        path = self.data_dir / filename
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def _index_one(self, filename: str, key: str) -> Mapping[str, Mapping[str, str]]:
        indexed = {row[key]: MappingProxyType(row) for row in self._read(filename)}
        return MappingProxyType(indexed)

    def _index_many(self, filename: str, key: str) -> Mapping[str, Sequence[Mapping[str, str]]]:
        grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
        for row in self._read(filename):
            grouped[row[key]].append(MappingProxyType(row))
        return MappingProxyType({value: tuple(rows) for value, rows in grouped.items()})

    def order(self, order_id: str) -> Mapping[str, str]:
        try:
            return self._orders[order_id]
        except KeyError as exc:
            raise KeyError(f"Order not found: {order_id}") from exc

    def items(self, order_id: str) -> Sequence[Mapping[str, str]]:
        return self._items.get(order_id, ())

    def payments(self, order_id: str) -> Sequence[Mapping[str, str]]:
        return self._payments.get(order_id, ())

    def seller_exists(self, seller_id: str) -> bool:
        return seller_id in self._sellers

