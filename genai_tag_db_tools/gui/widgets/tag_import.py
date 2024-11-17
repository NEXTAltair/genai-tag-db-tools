import logging
import traceback
from functools import partial

import polars as pl

from PySide6.QtCore import Slot, Qt, QAbstractTableModel, Signal
from PySide6.QtWidgets import QDialog, QMenu, QMessageBox

from genai_tag_db_tools.gui.designer.TagDataImportDialog_ui import (
    Ui_TagDataImportDialog,
)

from genai_tag_db_tools.core.import_data import TagDataImporter, ImportConfig
from genai_tag_db_tools.core.tag_search import TagSearcher
from genai_tag_db_tools.config import AVAILABLE_COLUMNS


class PolarsModel(QAbstractTableModel):
    mappingChanged = Signal()  # クラス属性として Signal を定義

    def __init__(self, data: pl.DataFrame):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self._data = data
        self.importer = TagDataImporter()
        self._headers = list(
            self._data.columns
        )  # デフォルトのヘッダーを維持､あれば既存のヘッダーを使用､なければ `column1` など
        self._mapping = {
            i: "未選択" for i in range(len(self._headers))
        }  # カラムマッピング

    def rowCount(self, parent=None):
        return self._data.height

    def columnCount(self, parent=None):
        return self._data.width

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        """
        データを取得します。

        Args:
            index (QModelIndex): 取得するデータのインデックス。
            role (Qt.ItemDataRole, optional): データの役割。デフォルトは DisplayRole。

        Returns:
            str:
                表示用のデータを文字列として返す。データが None の場合は空文字列を返す。
        """
        if not index.isValid():
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() < self._data.width:
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
        # ヘッダーの更新を通知｡一行目を一列ずつ更新する
        self.logger.debug(f"マッピング更新: {self._headers[column]} → {mapped_name}")
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, column, column)
        self.mappingChanged.emit()  # シグナルを発行

    def getMapping(self) -> dict[str, str]:
        """現在のマッピングを取得"""
        return {
            self._headers[col]: mapped
            for col, mapped in self._mapping.items()
            if mapped != "未選択"
        }

    def hasRequiredMapping(self, required_field: str) -> bool:
        """指定された必須フィールドがマッピングされているかを確認"""
        return required_field in self.getMapping().values()


class TagDataImportDialog(QDialog, Ui_TagDataImportDialog):
    def __init__(self, source_df: pl.DataFrame, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.setupUi(self)
        self.tag_searcher = TagSearcher()
        self.format_id = 0
        self.language = "None"

        # モデルの設定
        self.source_df = source_df
        self.model = PolarsModel(source_df)
        self.dataPreviewTable.setModel(self.model)

        self.importer = TagDataImporter()

        self.setupConnections()
        self.initializeUI()
        self.model.mappingChanged.connect(
            self.on_sourceTagCheckBox_stateChanged
        )  # シグナルに接続

    def initializeUI(self):
        """UI初期化"""
        formats = self.tag_searcher.get_tag_formats()
        langs = self.tag_searcher.get_tag_languages()

        # 検索とは違い `ALL` は不要なので消す
        formats = formats.filter(pl.col("format_name") != "All")
        langs = langs.filter(pl.col("language") != "All")

        self.formatComboBox.addItems(formats["format_name"].to_list())
        self.languageComboBox.addItems(langs["language"].to_list())
        # インポートボタンは初期状態で無効化
        self.importButton.setEnabled(False)

    def setupConnections(self):
        """UIコンポーネントのイベントとアクションを接続"""

        # テーブルヘッダーメニュー
        header = self.dataPreviewTable.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.showHeaderMenu)

        # インポーター(QObject)のシグナル接続
        self.importer.progress_updated.connect(self.update_progress)
        self.importer.process_finished.connect(self.import_finished)

    @Slot(int, str)
    def update_progress(self, progress: int, message: str):
        """進捗状況の更新"""
        self.setWindowTitle(f"インポート中... {progress}%, {message}")

    @Slot(str)
    def import_finished(self, process_name: str):
        """インポート完了時の処理"""
        self.importButton.setEnabled(True)
        self.setWindowTitle(f"インポート完了, {process_name}")
        QMessageBox.information(self, "完了", "インポートが完了しました。")
        self.accept()

    def setControlsEnabled(self, enabled: bool):
        """
        ダイアログ内の主要なUIコントロールを有効化または無効化する
        :param enabled: True で有効化、False で無効化
        """
        controls = [
            self.importButton,
            self.cancelButton,
            self.sourceTagCheckBox,
            self.languageComboBox,
            self.dataPreviewTable,
            # 必要に応じて他のコントロールを追加
        ]
        for control in controls:
            control.setEnabled(enabled)

    @Slot()
    def on_importButton_clicked(self):
        """
        インポートボタンのクリックイベントを処理。
        検証は既にマッピング時に行われているため、ここではインポート処理のみを実行。
        """
        mapping = self.model.getMapping()

        # データフレームのカラム名を直接リネーム
        new_df = self.source_df.rename(mapping)

        config = ImportConfig(
            format_id=self.format_id,
            language=self.languageComboBox.currentText(),
            column_names=list(mapping.values()),
        )

        try:
            # UI要素の状態を更新
            self.setControlsEnabled(False)
            self.cancelButton.setText("キャンセル")

            # インポート開始
            self.importer.import_data(new_df, config)
        except ValueError as e:
            self.logger.error("インポートエラー: %s", e)
            self.setControlsEnabled(True)

    @Slot()
    def on_sourceTagCheckBox_stateChanged(self):
        """カラムマッピング変更時に必須フィールドを検証し、インポートボタンの状態を更新

        tag カラムか source_tag カラムは常に必要

        フォーマが不明の場合､言語と訳語が選択されている場合､インポートボタンを有効化
        翻訳がない場合はフォーマットがある場合インポートボタンを有効化
        """
        mapping = self.model.getMapping()

        has_format = self.formatComboBox.currentText() != "unknown"
        has_language = self.languageComboBox.currentText() != "None"
        has_source_tag = "source_tag" in mapping.values()
        has_tag = "tag" in mapping.values()
        has_translation = "translation" in mapping.values()

        self.sourceTagCheckBox.setChecked(has_source_tag)
        self.tagCheckBox.setChecked(has_tag)
        self.deprecatedTagsCheckBox.setChecked("translation" in mapping.values())
        self.translationTagsCheckBox.setChecked(has_translation)

        if not has_source_tag and not has_tag:
            self.importButton.setEnabled(False)
            return
        if not has_format and not has_language:
            self.importButton.setEnabled(False)
            return
        if has_language and not has_translation:
            self.importButton.setEnabled(False)
            return

        self.importButton.setEnabled(True)

    @Slot()
    def on_cancelButton_clicked(self):
        """キャンセルボタンの処理"""
        if self.cancelButton.text() == "キャンセル":
            self.importer.cancel()
            self.importButton.setEnabled(True)
            self.setWindowTitle("キャンセル")
        else:
            self.reject()

    @Slot()
    def on_formatComboBox_currentTextChanged(self):
        """フォーマットが変更されたときの処理"""
        format_name = self.formatComboBox.currentText()
        self.format_id = self.tag_searcher.get_format_id(format_name)
        self.on_sourceTagCheckBox_stateChanged()

    @Slot()
    def on_languageComboBox_currentTextChanged(self):
        """言語が変更されたときの処理"""
        self.on_sourceTagCheckBox_stateChanged()

    def showHeaderMenu(self, pos):
        """ヘッダーの右クリックメニューを表示し、マッピングを設定する"""
        column = self.dataPreviewTable.horizontalHeader().logicalIndexAt(pos)
        menu = QMenu(self)

        # マッピング選択のサブメニューを作成
        mapping_menu = menu.addMenu("マッピング")
        for mapped_name in ["未選択"] + list(AVAILABLE_COLUMNS.keys()):
            action = mapping_menu.addAction(mapped_name)
            # アクションがトリガーされたときに対応するメソッドを呼び出す
            # functools.partialを使用して引数を渡す
            action.triggered.connect(
                partial(self.set_column_mapping, column, mapped_name)
            )

        # メニューを表示
        menu.exec(self.dataPreviewTable.horizontalHeader().mapToGlobal(pos))

    def set_column_mapping(self, column, mapped_name):
        """指定されたカラムにマッピングを設定する"""
        self.model.setMapping(column, mapped_name)


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
