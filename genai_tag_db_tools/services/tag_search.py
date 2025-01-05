import logging
from socket import MsgFlag
from typing import Optional

from genai_tag_db_tools.data.tag_repository import TagRepository
from genai_tag_db_tools.utils.messages import LogMessages, ErrorMessages

class TagSearcher:
    """
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # リポジトリはとりあえず自前でインスタンス化（本来はDIするのが望ましい）
        self.tag_repo = TagRepository()

    def convert_tag(self, search_tag: str, target_format_name: str) -> str:
        """
        入力された `search_tag` を指定フォーマットの「推奨タグ」に変換して返す。
        - alias=True の場合などは preferred_tag を取得して置き換え。
        - DBになければそのまま返す。
        - もしデータベース的に 'invalid tag' 扱いであれば無視する or ログ出し (運用次第)
        """

        # 1) 対象フォーマットID取得
        format_id = self.tag_repo.get_format_id(target_format_name)
        if format_id is None:
            msg = ErrorMessages.MISSING_TAG_FORMAT.format(format_name=target_format_name)
            self.logger.error(msg)
            return search_tag

        # 2) タグIDを検索 (完全一致検索にするか部分一致にするかは運用次第)
        tag_id = self.tag_repo.get_tag_id_by_name(search_tag, partial=False)
        if tag_id is None:
            # DBになければ変換しない
            return search_tag

        # 3) preferred_tag_id を取得 (alias=Trueのときに別タグを指している可能性)
        preferred_tag_id = self.tag_repo.find_preferred_tag(tag_id, format_id)
        if preferred_tag_id is None:
            # 対応する TagStatus がない or alias=False で自分自身がpreferred_tagになってるケース
            return search_tag

        # 4) preferred_tag_id から実際のタグ文字列を取得
        preferred_tag_obj = self.tag_repo.get_tag_by_id(preferred_tag_id)
        if not preferred_tag_obj:
            # DB異常 → 元のタグのまま返す
            return search_tag

        preferred_tag = preferred_tag_obj.tag
        if preferred_tag == "invalid tag":
            # FIXME: DB上に 'invalid tag' が登録されていたらどう扱うか？
            # ここでは「変換せず元のタグを返す」か、あるいは "" (空文字) にするなど運用次第
            self.logger.warning(f"「優先タグは {search_tag} に対して「無効なタグ」です。オリジナルを使用してください。」")
            return search_tag

        if search_tag != preferred_tag:
            self.logger.info(f"タグ '{search_tag}' は '{preferred_tag}' に変換されました")

        return preferred_tag

    def get_tag_types(self, format_name: str) -> list[str]:
        """
        指定フォーマットに紐づくタグタイプ名の一覧を取得する。
        """
        format_id = self.tag_repo.get_format_id(format_name)
        if format_id is None:
            return []

        # リポジトリの get_tag_types(format_id) を使う
        return self.tag_repo.get_tag_types(format_id)

    def get_tag_languages(self) -> list[str]:
        """
        DB上に登録されている言語の一覧を返す。
        """
        return self.tag_repo.get_tag_languages()

def initialize_tag_searcher() -> TagSearcher:
    return TagSearcher()


if __name__ == "__main__":
    word = "1boy"
    match_mode = "partial"
    prompt = "1boy, 1girl, 2boys, 2girls, 3boys, 3girls, 4boys, 4girls, 5boys"
    format_name = "e621"
    tagsearcher = initialize_tag_searcher()

    # 修正ポイント:
    # 旧コードでは for tag in prompt.split(", "): の中で convert_tag(prompt, format_name) を呼んでいた → バグ
    # → 修正し、tag を渡す
    tags = []
    for tag in prompt.split(", "):
        converted = tagsearcher.convert_tag(tag, format_name)
        tags.append(converted)
    clean_prompt = ", ".join(tags)

    print("元のプロンプト:", prompt)
    print("変換後のプロンプト:", clean_prompt)

    # タグタイプ一覧を取得
    types = tagsearcher.get_tag_types("e621")
    print("e621 のタグタイプ:", types)

    # 言語一覧を取得
    langs = tagsearcher.get_tag_languages()
    print("登録されている言語:", langs)
