# genai_tag_db_tools/gui/widgets/tag_register.py

from PySide6.QtWidgets import QWidget, QMessageBox
from PySide6.QtCore import Slot

from genai_tag_db_tools.gui.designer.TagRegisterWidget_ui import Ui_TagRegisterWidget
from genai_tag_db_tools.gui.designer.TagDataImportDialog_ui import Ui_TagDataImportDialog
from genai_tag_db_tools.utils.cleanup_str import TagCleaner

# 新しく使うサービスクラス
from genai_tag_db_tools.services.app_services import TagSearchService
from genai_tag_db_tools.services.app_services import TagRegisterService  # 上記例で追加したクラス

class TagRegisterWidget(QWidget, Ui_TagRegisterWidget):
    def __init__(self, parent=None,
                 search_service: TagSearchService = None,
                 register_service: TagRegisterService = None):
        super().__init__(parent)
        self.setupUi(self)

        # サービス層を受け取る
        # (DI: 依存性注入) テスト時などにモックや別実装が差し込めるようにするのがおすすめ
        self.search_service = search_service or TagSearchService()
        self.register_service = register_service or TagRegisterService()

        # サービスのエラーシグナルを、このWidgetのスロットに接続
        self.register_service.error_occurred.connect(self.on_service_error)

    def initialize(self):
        """
        旧: initialize(self, tag_searcher)
        新: サービスをコンストラクタでもらっているので引数不要に変更。
        """
        self.initialize_ui()

    def initialize_ui(self):
        # フォーマット一覧を取得し、コンボボックスにセット
        formats = self.search_service.get_tag_formats()  # TagSearchServiceから取得
        self.comboBoxFormat.clear()
        self.comboBoxFormat.addItems(formats)

        # 言語一覧を取得
        languages = self.search_service.get_tag_languages()
        self.comboBoxLanguage.clear()
        self.comboBoxLanguage.addItems(languages)

        # デフォルト値設定
        self.comboBoxLanguage.setCurrentText("japanese")
        self.on_comboBoxFormat_currentIndexChanged()  # 初回反映

    @Slot(int)
    def on_comboBoxFormat_currentIndexChanged(self, index=0):
        format_name = self.comboBoxFormat.currentText() or "danbooru"
        tag_types = self.search_service.get_tag_types(format_name)
        self.comboBoxType.clear()
        self.comboBoxType.addItems([""] + tag_types)

    @Slot()
    def on_pushButtonRegister_clicked(self):
        try:
            tag_info = self.get_tag_info()

            tag_id = self.register_service.register_or_update_tag(tag_info)
            # ここでDB操作中エラーがあればシグナルが発火→on_service_error
            self.display_tag_details(tag_id)
            self.clear_fields()

        except Exception as e:
            QMessageBox.warning(self, "エラー", str(e))
            self.textEditOutput.append(f"エラー: {str(e)}")

    @Slot()
    def on_pushButtonImport_clicked(self):
        """
        インポートダイアログを開く
        """
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        self.lineEditTag.setText(text)

    @Slot(str)
    def on_service_error(self, error_msg: str):
        # サービスから発行されたerror_occurredシグナルを受け取り、ポップアップ表示
        QMessageBox.critical(self, "登録エラー", f"DB登録中にエラー: {error_msg}")
        # あるいは self.textEditOutput.append(f"エラー: {error_msg}")

    def get_tag_info(self) -> dict:
        """
        フォームから入力された情報を取り出し、
        register_service.register_or_update_tag() へ渡すための dict にまとめる。
        """
        tag = self.lineEditTag.text().strip()
        source_tag = self.lineEditSourceTag.text().strip() or tag
        if not tag and not source_tag:
            raise ValueError("タグまたは元タグは必須です。")

        # クリーニング
        normalized_tag = TagCleaner.clean_tags(source_tag)  # (or .clean_format)

        return {
            "normalized_tag": normalized_tag,
            "source_tag": source_tag,
            "format_name": self.comboBoxFormat.currentText(),
            "type_name": self.comboBoxType.currentText(),
            "use_count": self.spinBoxUseCount.value(),
            "language": self.comboBoxLanguage.currentText(),
            "translation": self.lineEditTranslation.text(),
        }

    def display_tag_details(self, tag_id: int):
        """
        登録・更新したタグの詳細を取得してテキストエリアに表示。
        """
        details_df = self.register_service.get_tag_details(tag_id)
        if details_df.is_empty():
            self.textEditOutput.append(f"タグID {tag_id} の情報が見つかりません。")
            return

        # Polars -> pandas 互換メソッドがあれば .to_pandas() などもOK
        info = details_df.to_dicts()[0]  # 1行目をdictで取得
        result = []
        result.append(f"タグ情報 (ID: {tag_id}):")
        result.append(f"タグ: {info.get('tag')}")
        result.append(f"元タグ: {info.get('source_tag')}")
        result.append(f"フォーマット: {info.get('formats')}")
        result.append(f"タイプ: {info.get('types')}")
        result.append(f"使用回数: {info.get('total_usage_count')}")
        result.append(f"翻訳: {info.get('translations')}")
        result.append("-" * 40)

        self.textEditOutput.append("\n".join(result))

    def clear_fields(self):
        self.lineEditTag.clear()
        self.lineEditSourceTag.clear()
        self.comboBoxFormat.setCurrentIndex(0)
        self.comboBoxType.setCurrentIndex(0)
        self.spinBoxUseCount.setValue(0)
        self.comboBoxLanguage.setCurrentText("japanese")
        self.lineEditTranslation.clear()

if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    widget = TagRegisterWidget()
    widget.show()
    sys.exit(app.exec_())
