import logging

from genai_tag_db_tools.data.tag_repository import TagRepository
class TagSearcher:
    """タグ検索・変換等を行うビジネスロジッククラス"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # リポジトリはとりあえず自前でインスタンス化
        self.tag_repo = TagRepository()

    def convert_tag(self, search_tag: str, format_id: int) -> str:
        """
        入力された `search_tag` を指定フォーマットの「推奨タグ」に変換して返す。
        - alias=True の場合などは preferred_tag を取得して置き換え。
        - DBになければそのまま返す。
        - 'invalid tag' はログに残して元タグを返す。

        Args:
            search_tag (str): 変換対象のタグ
            format_id (int): 対象のフォーマットID

        Returns:
            str: 変換後のタグ
        """
        # 1) タグIDを検索 (完全一致検索)
        tag_id = self.tag_repo.get_tag_id_by_name(search_tag, partial=False)
        if tag_id is None:
            # DBになければ変換しない
            return search_tag

        # 2) preferred_tag_id を取得 (alias=Trueのときのみ)
        preferred_tag_id = self.tag_repo.find_preferred_tag(tag_id, format_id)
        if preferred_tag_id is None:
            # 対応する TagStatus がない場合はそのまま返す
            return search_tag

        # 3) preferred_tag_id から実際のタグ文字列を取得
        preferred_tag_obj = self.tag_repo.get_tag_by_id(preferred_tag_id)
        if not preferred_tag_obj:
            # DB異常 → 元のタグのまま返す
            return search_tag

        preferred_tag = preferred_tag_obj.tag
        if preferred_tag == "invalid tag":
            # ログを出しておいて、後で手動修正できるようにする
            self.logger.warning(
                f"[convert_tag] '{search_tag}' → 優先タグが 'invalid tag' です。"
                "オリジナルタグを使用します。"
            )
            return search_tag

        if search_tag != preferred_tag:
            self.logger.info(f"タグ '{search_tag}' は '{preferred_tag}' に変換されました")

        return preferred_tag

    def get_tag_types(self, format_name: str) -> list[str]:
        """
        指定フォーマットに紐づくタグタイプ名の一覧を取得する。

        Args:
            format_name (str): フォーマット名

        Returns:
            list[str]: タグタイプ名のリスト
        """
        format_id = self.tag_repo.get_format_id(format_name)
        if format_id is None:
            return []
        return self.tag_repo.get_tag_types(format_id)

    def get_tag_languages(self) -> list[str]:
        """
        DB上に登録されている言語の一覧を返す。

        Returns:
            list[str]: 言語コードのリスト
        """
        return self.tag_repo.get_tag_languages()

    def get_tag_formats(self) -> list[str]:
        """
        利用可能なタグフォーマットの一覧を取得する。

        Returns:
            list[str]: フォーマット名のリスト。
        """
        return self.tag_repo.get_tag_formats()

    def get_format_id(self, format_name: str) -> int:
        """
        フォーマット名からフォーマットIDを取得する。

        Args:
            format_name (str): フォーマット名

        Returns:
            int: フォーマットID
        """
        return self.tag_repo.get_format_id(format_name)

if __name__ == "__main__":
    word = "1boy"
    prompt = "1boy, 1girl, 2boys, 2girls, 3boys, 3girls, 4boys, 4girls, 5boys"
    format_name = "e621"

    tagsearcher = TagSearcher()

    # 単一タグを部分一致で変換してみる例
    # (複数ヒットした場合の挙動はリポジトリ側 or さらに上位で検討)
    converted_single = tagsearcher.convert_tag(word, format_name)
    print(f"[single] '{word}' → '{converted_single}'")

    # タグタイプ一覧を取得
    types = tagsearcher.get_tag_types("e621")
    print("e621 のタグタイプ:", types)

    # 言語一覧を取得
    langs = tagsearcher.get_tag_languages()
    print("登録されている言語:", langs)

    # フォーマット一覧を取得
    formats = tagsearcher.get_tag_formats()
    print("利用可能なフォーマット:", formats)
