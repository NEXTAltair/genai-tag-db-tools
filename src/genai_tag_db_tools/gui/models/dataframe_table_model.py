from __future__ import annotations

import polars as pl
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class DataFrameTableModel(QAbstractTableModel):
    """Qt table model for a Polars DataFrame."""

    def __init__(self, df: pl.DataFrame | None = None, parent=None) -> None:
        super().__init__(parent)
        self._df = df if df is not None else pl.DataFrame()
        self._columns = list(self._df.columns)

    def set_dataframe(self, df: pl.DataFrame | None, display_columns: list[str] | None = None) -> None:
        self.beginResetModel()
        self._df = df if df is not None else pl.DataFrame()
        if display_columns:
            self._columns = [col for col in display_columns if col in self._df.columns]
        else:
            self._columns = list(self._df.columns)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return self._df.height

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        if parent is not None and parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        if role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        try:
            column = self._columns[index.column()]
            value = self._df[index.row(), column]
        except Exception:
            return ""
        if value is None:
            if column in {"usage_count", "alias", "deprecated"}:
                return "—"
            return ""
        return str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if section >= len(self._columns):
                return ""
            return self._columns[section]
        return str(section + 1)

    def get_row(self, row: int) -> dict[str, object]:
        if row < 0 or row >= self._df.height:
            return {}
        return {col: self._df[row, col] for col in self._df.columns}
