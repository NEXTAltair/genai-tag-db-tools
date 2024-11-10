import sys
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QTableView,
    QHeaderView,
    QComboBox,
    QVBoxLayout,
)
from PySide6.QtCore import Qt, QModelIndex, QAbstractTableModel


class ComboBoxHeader(QHeaderView):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setSectionsMovable(True)  # セクションの移動を許可
        self.setSectionsClickable(True)  # セクションのクリックを許可
        self.combo_boxes = {}  # コンボボックスを格納する辞書

    def sectionSizeFromContents(self, logicalIndex):
        # コンボボックスのサイズに合わせてヘッダーのサイズを調整
        if logicalIndex in self.combo_boxes:
            return (
                self.combo_boxes[logicalIndex].sizeHint().width() + 10
            )  # 少し余裕を持たせる
        else:
            return super().sectionSizeFromContents(logicalIndex)

    def paintSection(self, painter, rect, logicalIndex):
        # コンボボックスを表示
        if logicalIndex in self.combo_boxes:
            combo_box = self.combo_boxes[logicalIndex]
            combo_box.setGeometry(rect)
            combo_box.show()
        else:
            super().paintSection(painter, rect, logicalIndex)

    def addComboBox(self, logicalIndex, items):
        # コンボボックスを追加
        combo_box = QComboBox(self)
        combo_box.addItems(items)
        combo_box.currentIndexChanged.connect(
            lambda index, li=logicalIndex: self.headerDataChanged.emit(
                self.orientation(), li, li
            )
        )  # 変更を検知
        self.combo_boxes[logicalIndex] = combo_box
        self.updateGeometries()


class MyTableModel(QAbstractTableModel):
    def __init__(self, data):
        super().__init__()
        self._data = data

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self._data[0]) if self._data else 0

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            row = index.row()
            col = index.column()
            return self._data[row][col]

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self._data[0][section]  # 最初の行をヘッダーとする


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        # サンプルデータ
        self.data = [
            ["Name", "Age", "City"],
            ["Alice", "25", "New York"],
            ["Bob", "30", "London"],
            ["Charlie", "28", "Paris"],
        ]

        self.model = MyTableModel(self.data)
        self.table_view = QTableView()
        self.table_view.setModel(self.model)

        # カスタムヘッダービュー
        header = ComboBoxHeader(Qt.Horizontal, self.table_view)
        header.addComboBox(
            0, ["名前", "氏名", "ユーザー名"]
        )  # 最初の列のヘッダーをコンボボックスにする
        self.table_view.setHorizontalHeader(header)

        layout = QVBoxLayout()
        layout.addWidget(self.table_view)
        self.setLayout(layout)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
