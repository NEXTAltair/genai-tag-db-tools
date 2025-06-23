# genai_tag_db_tools/gui/widgets/tag_import.py
import logging
from functools import partial

import polars as pl
from PySide6.QtCore import QAbstractTableModel, Qt, Signal, Slot
from PySide6.QtWidgets import QDialog, QMenu, QMessageBox

from genai_tag_db_tools.gui.designer.TagDataImportDialog_ui import (
    Ui_TagDataImportDialog,
)

# 新規作成したサービス層をインポート (TagImportService)
from genai_tag_db_tools.services.app_services import TagImportService
from genai_tag_db_tools.services.import_data import ImportConfig
from genai_tag_db_tools.services.polars_schema import AVAILABLE_COLUMNS


class PolarsModel(QAbstractTableModel):
    """
    Polars DataFrame の表示と、カラムマッピング（元カラム名→新カラム名）の管理を担当するモデル。
    DB操作やビジネスロジックは含まない。
    """

    mappingChanged = Signal()

    def __init__(self, data: pl.DataFrame):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self._data = data
        self._headers = list(self._data.columns)
        # 「カラムインデックス → '未選択' or カラム名」の辞書
        self._mapping = dict.fromkeys(range(len(self._headers)), "未選択")

    def rowCount(self, parent=None):
        return self._data.height

    def columnCount(self, parent=None):
        return self._data.width

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            value = self._data.item(index.row(), index.column())
            return str(value) if value is not None else ""
        return None

    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                original = self._headers[section]
                mapped = self._mapping[section]
                return f"{original} → {mapped}" if mapped != "未選択" else original
            if orientation == Qt.Orientation.Vertical:
                return str(section + 1)
        return None

    def setMapping(self, column: int, mapped_name: str):
        """
        指定カラムのマッピング名を設定。シグナルでUIに通知する。
        """
        old = self._mapping[column]
        self._mapping[column] = mapped_name
        self.logger.debug(f"マッピング更新: {self._headers[column]} → {mapped_name}, (old={old})")
        # ヘッダーラベルを再表示
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, column, column)
        self.mappingChanged.emit()

    def getMapping(self) -> dict[str, str]:
        """
        { "元カラム名": "新カラム名" } の辞書を返す。
        '未選択' は含めない。
        """
        return {self._headers[col]: mapped for col, mapped in self._mapping.items() if mapped != "未選択"}


class TagDataImportDialog(QDialog, Ui_TagDataImportDialog):
    """
    GUIダイアログ。DB操作やインポートロジックはサービス(TagImportService)に任せる。
    カラムマッピングやUI操作を担当。
    """

    def __init__(self, source_df: pl.DataFrame, service: TagImportService, parent=None):
        """
        コンストラクタで TagImportService を受け取り、GUI側で使う。
        source_df はプレビュー表示用のPolars DataFrame。
        """
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.setupUi(self)

        # サービス層 (DBロジック, TagDataImporter) を利用する窓口
        self._service = service
        self.source_df = source_df

        # PolarsModel を使ってプレビュー & カラムマッピング
        self.model = PolarsModel(self.source_df)
        self.dataPreviewTable.setModel(self.model)
        self.model.mappingChanged.connect(self.on_sourceTagCheckBox_stateChanged)

        # TagDataImporter のシグナルをGUIで受けたい場合は、ここで接続
        # (サービス内で公開している _importer シグナルを直接使う)
        self._service._importer.progress_updated.connect(self.update_progress)
        self._service._importer.process_finished.connect(self.import_finished)
        self._service._importer.error_occurred.connect(self.on_import_error)

        # UI初期状態設定
        self.initializeUI()

        # 他のUIイベントを接続
        self.setupConnections()

    def initializeUI(self):
        """
        GUI初期化: DBからフォーマット一覧や言語一覧を取得し、ComboBoxに表示する。
        """
        formats = self._service.get_tag_formats()
        langs = self._service.get_tag_languages()

        # コンボボックスに追加
        self.formatComboBox.addItems(formats)
        self.languageComboBox.addItems(langs)

        # インポートボタンは初期状態で無効化しておく
        self.importButton.setEnabled(False)

    def setupConnections(self):
        """
        UIコンポーネントのイベントを接続（ヘッダー右クリックメニューなど）
        """
        header = self.dataPreviewTable.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.showHeaderMenu)

    # --- シグナルのスロット ---

    @Slot(int, str)
    def update_progress(self, progress: int, message: str):
        """
        TagDataImporter からの進捗通知。ウィンドウタイトルに表示する例。
        """
        self.setWindowTitle(f"インポート中... {progress}%, {message}")

    @Slot(str)
    def import_finished(self, process_name: str):
        """
        インポート完了時。ボタン有効化やメッセージを表示する。
        """
        self.importButton.setEnabled(True)
        self.setWindowTitle(f"インポート完了: {process_name}")
        QMessageBox.information(self, "完了", "インポートが完了しました。")
        self.accept()

    @Slot(str)
    def on_import_error(self, message: str):
        """
        エラー発生時の処理: メッセージを表示し、UI操作を復帰。
        """
        QMessageBox.critical(self, "インポートエラー", message)
        self.setControlsEnabled(True)

    def setControlsEnabled(self, enabled: bool):
        """
        ダイアログ内の主要コントロールを一括で有効/無効にする。
        """
        controls = [
            self.importButton,
            self.cancelButton,
            self.sourceTagCheckBox,
            self.languageComboBox,
            self.dataPreviewTable,
        ]
        for c in controls:
            c.setEnabled(enabled)

    # --- ボタンやチェックボックスの操作 ---

    @Slot()
    def on_importButton_clicked(self):
        """
        インポートボタン押下: カラムマッピング + ImportConfig を組み立てて
        サービス層へ import_data を依頼する。
        """
        mapping = self.model.getMapping()
        # マッピングに従ってデータフレームをリネーム
        new_df = self.source_df.rename(mapping)

        config = ImportConfig(
            format_id=self._service.get_format_id(self.formatComboBox.currentText()),
            language=self.languageComboBox.currentText(),
            column_names=list(mapping.values()),
        )

        try:
            self.setControlsEnabled(False)
            self.cancelButton.setText("キャンセル")

            # 実際のインポート処理はサービス層に任せる
            self._service.import_data(new_df, config)

        except ValueError as e:
            self.logger.error(f"インポートエラー: {e}")
            self.setControlsEnabled(True)

    @Slot()
    def on_sourceTagCheckBox_stateChanged(self):
        """
        マッピング変更などのたびに呼ばれ、必須フィールドが揃っていればインポート可にする。
        """
        mapping = self.model.getMapping()

        has_source_tag = "source_tag" in mapping.values()
        has_tag = "tag" in mapping.values()
        has_translation = "translation" in mapping.values()

        self.sourceTagCheckBox.setChecked(has_source_tag)
        self.tagCheckBox.setChecked(has_tag)
        self.translationTagsCheckBox.setChecked(has_translation)
        self.deprecatedTagsCheckBox.setChecked("translation" in mapping.values())

        # コンボボックスの状態を確認
        format_chosen = bool(self.formatComboBox.currentText())
        language_chosen = self.languageComboBox.currentText() != "None"

        # 簡易バリデーション
        if not has_source_tag and not has_tag:
            self.importButton.setEnabled(False)
            return
        if not format_chosen and not language_chosen:
            self.importButton.setEnabled(False)
            return
        if language_chosen and not has_translation:
            self.importButton.setEnabled(False)
            return

        self.importButton.setEnabled(True)

    @Slot()
    def on_cancelButton_clicked(self):
        """
        キャンセルボタン。途中キャンセル or ダイアログ閉じる動作を切り替える。
        """
        if self.cancelButton.text() == "キャンセル":
            self._service.cancel_import()
            self.importButton.setEnabled(True)
            self.setWindowTitle("キャンセル")
        else:
            self.reject()

    @Slot()
    def on_formatComboBox_currentTextChanged(self):
        """
        フォーマットが変更されたら必須フィールドチェックを更新。
        """
        self.on_sourceTagCheckBox_stateChanged()

    @Slot()
    def on_languageComboBox_currentTextChanged(self):
        """
        言語が変更されたら必須フィールドチェックを更新。
        """
        self.on_sourceTagCheckBox_stateChanged()

    def showHeaderMenu(self, pos_or_column):
        """
        テーブルヘッダを右クリックした際のマッピング設定メニュー。

        Args:
            pos_or_column: QPointの場合はクリック位置、intの場合は直接カラムインデックス
        """
        if isinstance(pos_or_column, int):
            column = pos_or_column
        else:
            column = self.dataPreviewTable.horizontalHeader().logicalIndexAt(pos_or_column)

        menu = QMenu(self)

        # マッピング選択のサブメニューを作成
        mapping_menu = menu.addMenu("マッピング")
        for mapped_name in ["未選択"] + list(AVAILABLE_COLUMNS.keys()):
            action = mapping_menu.addAction(mapped_name)
            # アクションがトリガーされたときに対応するメソッドを呼び出す
            # functools.partialを使用して引数を渡す
            action.triggered.connect(partial(self.set_column_mapping, column, mapped_name))

        if not isinstance(pos_or_column, int):
            menu.exec(self.dataPreviewTable.horizontalHeader().mapToGlobal(pos_or_column))

    def set_column_mapping(self, column, mapped_name):
        """指定されたカラムにマッピングを設定する"""
        self.model.setMapping(column, mapped_name)


if __name__ == "__main__":
    """
    単体起動テスト用。テスト用CSVを読み込み、TagImportServiceを生成してダイアログを起動。
    """
    import sys
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    # テスト用CSV (例)
    csv_path = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "resource" / "case_03.csv"
    df = pl.read_csv(csv_path, has_header=False)

    # サービス層を生成
    from genai_tag_db_tools.services.app_services import TagImportService

    service = TagImportService()

    app = QApplication(sys.argv)
    dialog = TagDataImportDialog(df, service)
    dialog.show()
    sys.exit(app.exec())
