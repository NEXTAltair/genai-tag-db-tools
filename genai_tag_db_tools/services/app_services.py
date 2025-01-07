import logging
from genai_tag_db_tools.services.tag_search import TagSearcher

class TagCleanerService:
    """
    DBのフォーマット一覧を参照しつつ、複数タグをまとめて変換するサービスクラス。
    GUIなどでのタグ整形機能を想定。
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # TagSearcherを内部利用してDBからフォーマット一覧などを取得する
        self._tag_searcher = TagSearcher()

    def get_tag_formats(self) -> list[str]:
        """
        DBから取得したフォーマット一覧を返す。
        'All' を先頭に追加し、ユーザーが「すべてのフォーマット」を選べるようにする想定。
        """
        format_list = ["All"]  # すべてのフォーマットを選択するための特別な項目
        format_list.extend(self._tag_searcher.get_tag_formats())
        return format_list

    def convert_prompt(self, prompt: str, format_name: str) -> str:
        """
        文字列中に含まれる複数タグをDBから検索・変換して返す。
        例:
            prompt = "1boy, 1girl, 2girls"
            format_name = "e621"
            → DBを参照して各タグを 'convert_tag' し、結果をまとめて返す。

        Args:
            text (str): カンマ区切りのタグ列を想定
            format_name (str): 変換対象フォーマット

        Returns:
            str: 変換後のタグ列 (同じ区切り文字で連結)
        """
        # TODO: loraの<>や()の処理はあとで考える
        format_id = self._tag_searcher.get_format_id(format_name)
        # タグをカンマ区切りで分割し、各タグを TagSearcher.convert_tag() で変換
        raw_tags = [t.strip() for t in prompt.split(",")]
        converted_list = []
        for tag in raw_tags:
            converted = self._tag_searcher.convert_tag(tag, format_id)
            converted_list.append(converted)

        # 再度カンマ区切りで連結して返す
        return ", ".join(converted_list)


if __name__ == "__main__":
    cleaner = TagCleanerService()
    all_formats = cleaner.get_tag_formats()
    print("DBから取得したフォーマット一覧:", all_formats)

    sample_text = "1boy, 1girl, 2boys"
    format_name = "e621"
    result = cleaner.convert_prompt(sample_text, format_name)
    print(f"[convert_prompt] '{sample_text}' → '{result}' (format='{format_name}')")
