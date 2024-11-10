"""
from PySide6.QtCore import Slot, Qt, QAbstractTableModel
"""

import polars as pl
from PySide6.QtCore import Slot, Qt, QAbstractTableModel, QPoint
from PySide6.QtWidgets import QDialog, QMenu, QMessageBox

from genai_tag_db_tools.gui.designer.TagDataImportDialog_ui import Ui_TagDataImportDialog
from genai_tag_db_tools.core.import_data import TagDataImporter, ImportConfig
from genai_tag_db_tools import db_path, AVAILABLE_COLUMNS


class PolarsModel(QAbstractTableModel):
    def __init__(self, data: pl.DataFrame):
        super().__init__()
        self._data = data
        self.importer = TagDataImporter()
        self._headers = list(self._data.columns)  # カラム名を保持
        self._mapping = {
            i: "未選択" for i in range(len(self._headers))
        }  # カラムマッピング

    def rowCount(self, parent=None):
        return self._data.height

    def columnCount(self, parent=None):
        return self._data.width

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            value = self._data[index.row(), index.column()]
            return str(value) if value is not None else ""

        return None

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                # マッピング情報も表示
                mapped = self._mapping[section]
                original = self._headers[section]
                return f"{original} → {mapped}" if mapped != "未選択" else original
            if orientation == Qt.Orientation.Vertical:
                return str(section + 1)
        return None

    def setMapping(self, column: int, mapped_name: str):
        """カラムのマッピングを設定"""
        self._mapping[column] = mapped_name
        # ヘッダーの更新を通知
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, column, column)

    def getMapping(self) -> dict[str, str]:
        """現在のマッピングを取得"""
        return {
            self._headers[col]: mapped
            for col, mapped in self._mapping.items()
            if mapped != "未選択"
        }


class TagDataImportDialog(QDialog, Ui_TagDataImportDialog):
    def __init__(self, source_df: pl.DataFrame, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # モデルの設定
        self.model = PolarsModel(source_df)
        self.dataPreviewTable.setModel(self.model)

        self.importer = TagDataImporter()

        self.setupConnections()
        self.initializeUI()

    def initializeUI(self):
        """UI初期化"""
        # インポートボタンは初期状態で無効化
        self.importButton.setEnabled(False)

    def setupConnections(self):
        """UIコンポーネントのイベントとアクションを接続"""
        self.sourceTagCheckBox.stateChanged.connect(
            self.on_sourceTagCheckBox_stateChanged
        )
        self.tagCheckBox.stateChanged.connect(self.on_sourceTagCheckBox_stateChanged)

        # テーブルヘッダーメニュー
        header = self.dataPreviewTable.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.showHeaderMenu)

        # インポーターのシグナル接続
        self.importer.progress_updated.connect(self.updateProgress)
        self.importer.process_started.connect(self.onImportStarted)
        self.importer.process_finished.connect(self.onImportFinished)
        self.importer.error_occurred.connect(self.onImportError)

    @Slot(int, str)
    def updateProgress(self, progress: int, message: str):
        """進捗状況の更新"""
        self.setWindowTitle(f"インポート中... {progress}%")

    @Slot(str)
    def onImportStarted(self, process_name: str):
        """インポート開始時の処理"""
        self.setWindowTitle("インポート開始")
        self.importButton.setEnabled(False)

    @Slot(str)
    def onImportFinished(self, process_name: str):
        """インポート完了時の処理"""
        self.importButton.setEnabled(True)
        self.setWindowTitle("インポート完了")
        QMessageBox.information(self, "完了", "インポートが完了しました。")
        self.accept()

    @Slot(str)
    def onImportError(self, error_message: str):
        """エラー発生時の処理"""
        self.importButton.setEnabled(True)
        self.setWindowTitle("エラー")
        QMessageBox.critical(
            self, "エラー", f"インポート中にエラーが発生しました: {error_message}"
        )

    @Slot()
    def on_import_button_clicked(self):
        """
        インポートボタンのクリックイベントを処理。
        """
        if not self.on_sourceTagCheckBox_stateChanged():
            QMessageBox.warning(
                self,
                "検証エラー",
                "必須フィールドが選択されていません。source_tagは必須です。",
            )
            return

        try:
            mapping = self.model.getMapping()
            selected_columns = list(mapping.keys())
            df = self.model._data.select(selected_columns)

            config = ImportConfig(
                format_id=self.getFormatId(),
                language=self.languageComboBox.currentText(),
                column_names=selected_columns,
            )

            # UI要素の状態を更新
            self.setControlsEnabled(False)
            self.cancelButton.setText("キャンセル")

            # インポート開始
            self.importer.import_data(df, config)

        except Exception as e:
            self.onImportError(str(e))

    def on_cancelButton_clicked(self):
        """キャンセルボタンの処理"""
        if self.cancelButton.text() == "キャンセル":
            self.importer.cancel()
            self.importButton.setEnabled(True)
            self.setWindowTitle("キャンセル")
        else:
            self.reject()

    def getFormatId(self) -> int:
        """選択されたフォーマットIDを取得"""
        format_map = {"danbooru": 1, "e621": 2, "derpibooru": 3}
        return format_map.get(self.formatComboBox.currentText(), 0)

    def importData(self):
        """データのインポート処理"""
        mapping = self.model.getMapping()
        selected_columns = list(mapping.keys())
        df = self.model._data.select(selected_columns)  # 必要なカラムを選択

        importer = TagDataImporter()
        config = importer.configure_import(df)
        importer.import_data(df, config)

        QMessageBox.information(
            self, "インポート完了", "データのインポートが完了しました。"
        )

    def on_formatComboBox_currentTextChanged(self):
        """フォーマットが変更されたときの処理"""
        # フォーマットに応じて利用可能なタイプを更新するなど
        self.on_sourceTagCheckBox_stateChanged()

    def on_languageComboBox_currentTextChanged(self, language: str):
        """言語が変更されたときの処理"""
        self.on_sourceTagCheckBox_stateChanged()

    def on_sourceTagCheckBox_stateChanged(self) -> bool:
        """必須フィールドの検証"""
        # source_tagのマッピングが存在するか確認
        mapping = self.model.getMapping()
        has_source_tag = "source_tag" in mapping.values()

        # インポートボタンの有効/無効を設定
        self.importButton.setEnabled(has_source_tag)

        # source_tagチェックボックスの状態を更新
        self.sourceTagCheckBox.setChecked(has_source_tag)

        return has_source_tag

    def on_previewButton_clicked(self):
        """プレビューの更新"""
        # マッピング情報の更新
        self.on_sourceTagCheckBox_stateChanged()

        # テーブルの表示を更新
        self.model.layoutChanged.emit()

        # 現在の設定でインポート可能かチェック
        can_import = self.on_sourceTagCheckBox_stateChanged()
        self.importButton.setEnabled(can_import)

    def showHeaderMenu(self, pos):
        """ヘッダーの右クリックメニュー"""
        column = self.dataPreviewTable.horizontalHeader().logicalIndexAt(pos)
        menu = QMenu(self)

        # マッピング選択のサブメニュー
        mapping_menu = menu.addMenu("マッピング")
        for mapped_name in ["未選択", "source_tag", "tag", "type_id", "translation"]:
            action = mapping_menu.addAction(mapped_name)
            action.triggered.connect(
                lambda checked, col=column, name=mapped_name=mapped_name: self.model.setMapping(
                    col, name
                )
            )

        menu.exec_(self.dataPreviewTable.horizontalHeader().mapToGlobal(pos))


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    csv_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "tests"
        / "resource"
        / "case_03.csv"
    )
    df = pl.read_csv(csv_path, has_header=False)
    app = QApplication(sys.argv)
    window = TagDataImportDialog(df)
    window.show()
    sys.exit(app.exec())
