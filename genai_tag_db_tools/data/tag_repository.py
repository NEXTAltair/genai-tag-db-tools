from logging import getLogger
from typing import Optional
import polars as pl
from sqlalchemy.orm import sessionmaker, scoped_session, aliased
from sqlalchemy import or_
import polars as pl
from genai_tag_db_tools.db.database_setup import SessionLocal
from genai_tag_db_tools.data.database_schema import (
    Tag,
    TagStatus,
    TagTranslation,
    TagFormat,
    TagTypeName,
    TagTypeFormatMapping,
    TagUsageCounts,
)


class TagRepository:
    logger = getLogger(__name__)
    """
    タグおよび関連テーブルへのアクセスを一元管理するリポジトリクラス

    主に以下のテーブルを扱う:
      - TAGS
      - TAG_FORMATS
      - TAG_TYPE_NAME
      - TAG_STATUS
      - TAG_USAGE_COUNTS
      - TAG_TRANSLATIONS
      - TAG_FORMATS / TAG_TYPE_NAME / TAG_TYPE_FORMAT_MAPPING (検索系)
    """
    def __init__(self):
        self.session_factory = SessionLocal

    # --- TAG CRUD ---
    def create_tag(self, source_tag: str, tag: str) -> int:
        """
        単一の (source_tag, tag) を受け取り、
        DBに新規タグを登録する。
        すでに同じ tag_name がある場合は既存のtag_idを返す。

        Args:
            source_tag (str): ソースタグ
            tag (str): タグ

        Returns:
            int: 作成(または取得)したタグID
        """
        # 1) 同名tagの有無をチェック
        existing_id = self.get_tag_id_by_name(tag, partial=False)
        if existing_id is not None:
            return existing_id

        # 2) 新規作成
        new_tag_data = {"source_tag": source_tag, "tag": tag}
        df = pl.DataFrame(new_tag_data)
        self.bulk_insert_tags(df)

        # 3) もう一度 ID を取得して返す
        tag_id = self.get_tag_id_by_name(tag, partial=False)
        if tag_id is None:
            raise ValueError("挿入後にタグ ID が見つかりませんでした。")
        return tag_id

    def get_tag_id_by_name(self, keyword: str, partial: bool = False) -> Optional[int]:
        """
        TAGSテーブルからタグIDを検索する。
        部分一致やワイルドカード `*` をサポート。

        Args:
            keyword (str): 検索キーワード
                例: 'cat', 'ca*', '*cat*'
            partial (bool): TrueならLIKE検索、Falseなら完全一致検索

        Returns:
            Optional[int]: タグID。見つからない場合None。

        Raises:
            ValueError: 複数のタグがヒットした場合（仕様次第で挙動変更可）。
        """
        # 'cat*' などユーザーが入力した場合 '*' を '%' に置き換え
        if '*' in keyword:
            keyword = keyword.replace('*', '%')

        with self.session_factory() as session:
            query = session.query(Tag)

            # partial=True or 置換後に'%'が含まれる なら LIKE検索
            if partial or '%' in keyword:
                # 部分一致用に補助。必要なら "%keyword%" に付け足すなど
                if not keyword.startswith('%'):
                    keyword = '%' + keyword
                if not keyword.endswith('%'):
                    keyword = keyword + '%'
                query = query.filter(Tag.tag.like(keyword))
            else:
                # 完全一致
                query = query.filter(Tag.tag == keyword)

            results = query.all()

            if not results:
                return None
            if len(results) == 1:
                return results[0].tag_id

            if partial or '%' in keyword:
                # 部分一致/ワイルドカード -> 先頭を返す
                # TODO: この処理は後で調整
                return results[0].tag_id
            else:
                # 完全一致で2件以上はエラー
                raise ValueError(f"複数ヒット: {results}")

    def get_tag_by_id(self, tag_id: int) -> Optional[Tag]:
        """
        指定されたtag_idに対応するTagオブジェクトをデータベースから取得

        Tagオブジェクトは、データベース内のTAGテーブルの1レコードを表す構造体
        通常、tag_idとtag_nameなどの属性を持つ

        Args:
            tag_id (int): 検索対象のタグID

        Returns:
            Optional[Tag]:
                - 一致するTagオブジェクトが見つかった場合、そのオブジェクトを返す。
                - 一致するTagオブジェクトが見つからなかった場合、Noneを返す。

        Raises:
            SQLAlchemyError: データベース操作中にエラーが発生した場合
        """
        with self.session_factory() as session:
            return session.query(Tag).filter(Tag.tag_id == tag_id).one_or_none()

    def update_tag(self, tag_id: int, *, source_tag: Optional[str] = None, tag: Optional[str] = None) -> None:
        """
        タグIDを指定して、タグ情報を更新する。
        # HACK: 常にペアで更新するようにすれば片方が None の処理は不要かもしれない

        Args:
            tag_id (int): 更新対象のタグID
            source_tag (Optional[str]): ソースタグ
            tag (Optional[str]): タグ

        Returns:
            None
        """
        with self.session_factory() as session:
            tag_obj = session.query(Tag).get(tag_id)
            if not tag_obj:
                raise ValueError(f"存在しないタグID {tag_id} の更新を試みました。")
            if source_tag is not None:
                tag_obj.source_tag = source_tag
            if tag is not None:
                tag_obj.tag = tag
            session.commit()

    def delete_tag(self, tag_id: int) -> None:
        """
        タグIDを指定して、タグを削除する。
        # WARNING: 一応作ったが、実際に使うかは要検討｡ 他テーブルとの整合性を破壊する可能性あり

        Args:
            tag_id (int): 削除対象のタグID
        """
        with self.session_factory() as session:
            tag_obj = session.query(Tag).get(tag_id)
            if tag_obj:
                session.delete(tag_obj)
                session.commit()

    def list_tags(self) -> list[Tag]:
        """
        タグテーブルに登録されている全てのタグを取得する。

        Returns:
            list[Tag]: タグテーブルに登録されている全てのタグのオブジェクトが格納されたリスト
        """
        with self.session_factory() as session:
            return session.query(Tag).all()

    def bulk_insert_tags(self, df: pl.DataFrame) -> None:
        """
        import_data.py で使う
        複数の (source_tag, tag) を一括登録。
        すでに存在するものはスキップする

        Args:
            df (pl.DataFrame): source_tag, tag の2カラムを持つDataFrame
        """
        required_cols = {"source_tag", "tag"}
        if not required_cols.issubset(set(df.columns)):
            missing = required_cols - set(df.columns)
            raise ValueError(f"DataFrameに{missing}カラムがありません。")

        # 既存タグの取得
        unique_tag_list = df["tag"].unique().to_list()
        existing_tag_map = self._fetch_existing_tags_as_map(unique_tag_list)
        # ↑ 例: SELECT tag, tag_id FROM TAGS WHERE tag IN (...)

        # 新規タグ行だけ抽出
        new_df = df.filter(~pl.col("tag").is_in(list(existing_tag_map.keys())))

        if new_df.is_empty():
            return  # 全部既存

        records = new_df.select(["source_tag", "tag"]).to_dicts()

        with self.session_factory() as session:
            session.bulk_insert_mappings(Tag, records)
            session.commit()

    def _fetch_existing_tags_as_map(self, tag_list: list[str]) -> dict[str, int]:
        """
        登録しようとするタグ名リストに対して､すでに存在するかを確認する
        例: SELECT tag, tag_id FROM TAGS WHERE tag in (..)
        戻り値: {tag: tag_id, ...}

        Args:
            tag_list (list[str]): タグリスト

        Returns:
            dict[str, int]: タグをキーとしたタグIDの辞書
        """
        with self.session_factory() as session:
            existing_tags = (
                session.query(Tag.tag, Tag.tag_id)
                .filter(Tag.tag.in_(tag_list))
                .all()
            )
            return {tag: tag_id for tag, tag_id in existing_tags}


    # --- TAG_FORMATS ---
    def get_format_id(self, format_name: str) -> Optional[int]:
        """
        指定されたフォーマット名に対応するフォーマットIDを取得する。

        Args:
            format_name (str): フォーマット名

        Returns:
            Optional[int]: フォーマットID。見つからない場合None。
        """
        with self.session_factory() as session:
            format_obj = session.query(TagFormat).filter(TagFormat.format_name == format_name).one_or_none()
            return format_obj.format_id if format_obj else None


    # --- TAG_TYPE_NAME ---
    def get_type_id(self, type_name: str) -> Optional[int]:
        """
        指定されたタイプ名に対応するタイプIDを取得する。

        Args:
            type_name (str): タイプ名

        Returns:
            Optional[int]: タイプID。見つからない場合None。
        """
        with self.session_factory() as session:
            type_obj = session.query(TagTypeName).filter(TagTypeName.type_name == type_name).one_or_none()
            return type_obj.type_name_id if type_obj else None


    # --- TAG_STATUS ---
    def get_tag_status(self, tag_id: int, format_id: int) -> Optional[TagStatus]:
        """
        指定された tag_id, format_id に対する TagStatus を1件取得。
        見つからなければ None を返す。

        Args:
            tag_id (int): タグID
            format_id (int): フォーマットID

        Returns:
            Optional[TagStatus]: TagStatusオブジェクト
        """
        with self.session_factory() as session:
            return (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )

    def update_tag_status(self, tag_id: int, format_id: int, type_id: int,
                          alias: bool, preferred_tag_id: int) -> None:
        """
        TAG_STATUS テーブルを新規作成。
        既存レコードが無ければINSERT、あればValueErrorを投げる。

        Args:
            tag_id (int): タグID
            format_id (int): フォーマットID
            type_id (int): タイプID
            alias (bool): 非推奨タグかどうか
            preferred_tag_id (int): 優先タグID
        """
        with self.session_factory() as session:
            status_obj = (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )

            if status_obj:
                # 既存レコードがあればエラー
                # TODO: GUIでその都度目視で確認するか、上書きするか選択できるようにする
                raise ValueError(f"既に存在するタグステータス: {status_obj}")
            else:
                # 新規作成
                status_obj = TagStatus(
                    tag_id=tag_id,
                    format_id=format_id,
                    type_id=type_id,
                    alias=alias,
                    preferred_tag_id=preferred_tag_id,
                )
                session.add(status_obj)
            session.commit()

    def delete_tag_status(self, tag_id: int, format_id: int) -> None:
        """
        指定された (tag_id, format_id) の TagStatus を削除。
        # WARNING: 使わない想定｡他テーブルとの整合性を破壊する可能性あり

        Args:
            tag_id (int): タグID
            format_id (int): フォーマットID
        """
        with self.session_factory() as session:
            status_obj = (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )
            if status_obj:
                session.delete(status_obj)
                session.commit()

    def list_tag_statuses(self, tag_id: Optional[int] = None) -> list[TagStatus]:
        """
        複数のステータスをまとめて取得。
        tag_idが指定されていればそのタグだけ、指定されなければ全件。

        Args:
            tag_id (Optional[int]): タグID

        Returns:
            list[TagStatus]: TagStatusオブジェクトのリスト
            - tag_id が指定されている場合はそのタグのステータスのみ
            - tag_id が指定されていない場合は全てのステータス
        """
        with self.session_factory() as session:
            query = session.query(TagStatus)
            if tag_id is not None:
                query = query.filter(TagStatus.tag_id == tag_id)
            return query.all()

    # --- TAG_USAGE_COUNTS ---
    def get_usage_count(self, tag_id: int, format_id: int) -> Optional[int]:
        """
        TAG_USAGE_COUNTS テーブルから使用回数を取得。
        見つからなければ None を返す。

        Args:
            tag_id (int): タグID
            format_id (int): フォーマットID

        Returns:
            Optional[int]: 使用回数
        """
        with self.session_factory() as session:
            usage_obj = (
                session.query(TagUsageCounts)
                .filter(TagUsageCounts.tag_id == tag_id, TagUsageCounts.format_id == format_id)
                .one_or_none()
            )
            return usage_obj.count if usage_obj else None

    def update_usage_count(self, tag_id: int, format_id: int, count: int) -> None:
        """
        TAG_USAGE_COUNTS テーブルの使用回数を更新または新規作成。

        Args:
            tag_id (int): タグID
            format_id (int): フォーマットID
            count (int): 使用回数
        """
        with self.session_factory() as session:
            usage_obj = (
                session.query(TagUsageCounts)
                .filter(TagUsageCounts.tag_id == tag_id, TagUsageCounts.format_id == format_id)
                .one_or_none()
            )

            if usage_obj:
                # 既存レコードがあれば更新
                # NOTE: 確認せずに上書きするが、そこまで厳密でないので問題はないはず
                usage_obj.count = count
            else:
                # 新規作成
                usage_obj = TagUsageCounts(tag_id=tag_id, format_id=format_id, count=count)
                session.add(usage_obj)
            session.commit()

    # --- TAG_TRANSLATIONS ---
    def get_translations(self, tag_id: int) -> list[TagTranslation]:
        """
        指定された tag_id に対する翻訳情報を全て取得。

        Args:
            tag_id (int): タグID

        Returns:
            list[TagTranslation]: TagTranslationオブジェクトのリスト
        """
        with self.session_factory() as session:
            return session.query(TagTranslation).filter(TagTranslation.tag_id == tag_id).all()

    def add_or_update_translation(self, tag_id: int, language: str, translation: str) -> None:
        """
        TAG_TRANSLATIONS テーブルに翻訳を追加または更新。

        Args:
            tag_id (int): タグID
            language (str): 言語
            translation (str): 翻訳
        """
        with self.session_factory() as session:
            # 1) 事前に全て同じ行があるかを確認
            existing = (
                session.query(TagTranslation)
                .filter(
                    TagTranslation.tag_id == tag_id,
                    TagTranslation.language == language,
                    TagTranslation.translation == translation
                )
                .one_or_none()
            )

            # 2) 同じ行があればスキップ
            if existing:
                # 同じ3列が全て同じ = 完全重複 => 何も更新しない
                return

            #  "完全一致ならスキップ、それ以外なら新規作成"
            # 4) 新規作成
            translation_obj = TagTranslation(
                tag_id=tag_id,
                language=language,
                translation=translation
            )
            session.add(translation_obj)
            session.commit()

    # --- 複雑検索 ---
    def search_tags(
        self,
        keyword: str,
        partial: bool = True,
        format_name: str = "All"
    ) -> list[dict]:
        """
        複数テーブルをJOINし、タグ・翻訳・ステータス・使用回数などをまとめて検索。

        Args:
            keyword (str): 検索キーワード
            partial (bool): Trueなら部分一致、Falseなら完全一致
            format_name (str): 'All'（すべて）または特定のフォーマット名

        Returns:
            list[dict]:
                [
                {
                    'tag_id': int,
                    'tag': str,
                    'source_tag': str,
                    'language': str,
                    'translation': str,
                    'alias': bool,
                    'preferred_tag': str,
                    'format_name': str,
                    'usage_count': int,
                    'type_name': str
                },
                ...
                ]
        """

        # 1) session 取得
        with self.session_factory() as session:
            PreferredTag = aliased(Tag, name="PreferredTag")
            # 2) 基本クエリ構築
            #   モデル名: Tag, TagTranslation, TagStatus, TagFormat, TagUsageCounts, TagTypeName
            #   カラムを指定し、outerjoinしていく
            query = (
                session.query(
                    Tag.tag_id,
                    Tag.tag,
                    Tag.source_tag,
                    TagTranslation.language,
                    TagTranslation.translation,
                    TagStatus.alias,
                    # 「preferred_tag」 は TagStatus.preferred_tag_id をJOINして Tag.tag を取りたい場合
                    PreferredTag.tag.label("preferred_tag"),
                    TagFormat.format_name,
                    TagUsageCounts.count.label("usage_count"),
                    TagTypeName.type_name,
                )
                # JOIN構造はORM定義(relationship)か、明示的に outerjoin(モデル, 条件)
                # 例: outerjoin(TagTranslation, Tag.tag_id==TagTranslation.tag_id), ...
                .outerjoin(TagTranslation, Tag.tag_id == TagTranslation.tag_id)
                .outerjoin(TagStatus, Tag.tag_id == TagStatus.tag_id)
                .outerjoin(TagFormat, TagStatus.format_id == TagFormat.format_id)
                .outerjoin(TagUsageCounts, (Tag.tag_id == TagUsageCounts.tag_id) & (TagStatus.format_id == TagUsageCounts.format_id))
                # preferred_tag も TagsをJOIN
                .outerjoin(PreferredTag, TagStatus.preferred_tag_id == PreferredTag.tag_id)
                .outerjoin(TagTypeFormatMapping, (TagStatus.format_id == TagTypeFormatMapping.format_id) & (TagStatus.type_id == TagTypeFormatMapping.type_id))
                .outerjoin(TagTypeName, TagTypeFormatMapping.type_name_id == TagTypeName.type_name_id)
            )

            # 3) 部分一致 or 完全一致のフィルタ
            if partial:
                # 部分一致: tag OR translation が "%keyword%"
                like_keyword = f"%{keyword}%"
                query = query.filter(
                    or_(
                        Tag.tag.like(like_keyword),
                        TagTranslation.translation.like(like_keyword)
                    )
                )
            else:
                # 完全一致: tag OR translation == keyword
                query = query.filter(
                    or_(
                        Tag.tag == keyword,
                        TagTranslation.translation == keyword
                    )
                )

            # 4) フォーマット指定があればフィルタ
            if format_name != "All":
                query = query.filter(TagFormat.format_name == format_name)

            # 5) 実行
            rows = query.all()

        # 6) 結果を list[dict] へ整形
        result_list = []
        for row in rows:
            # row は namedtuple or sqlalchemy.util._collections.result
            # usage_count が None なら 0 に変換
            usage_count = row.usage_count if row.usage_count is not None else 0

            result_list.append({
                "tag_id": row.tag_id,
                "tag": row.tag,
                "source_tag": row.source_tag,
                "language": row.language,
                "translation": row.translation,
                "alias": row.alias,
                "preferred_tag": row.preferred_tag,
                "format_name": row.format_name,
                "usage_count": usage_count,
                "type_name": row.type_name,
            })

        return result_list

    def find_preferred_tag(self, tag_id: int, format_id: int) -> Optional[int]:
        """
        タグIDとフォーマットIDを指定して、優先タグIDを取得する。

        Args:
            tag_id (int): タグID
            format_id (int): フォーマットID

        Returns:
            Optional[int]: 優先タグID。見つからない場合None。
        """
        with self.session_factory() as session:
            status_obj = (
                session.query(TagStatus)
                .filter(TagStatus.tag_id == tag_id, TagStatus.format_id == format_id)
                .one_or_none()
            )
            return status_obj.preferred_tag_id if status_obj else None

    # --- リスト取得 ---
    def get_all_tag_ids(self) -> list[int]:
        """
        TAGテーブルからすべてのタグIDを取得する
        Returns:
            list[int]: すべてのタグIDのリスト。
        """
        with self.session_factory() as session:
            return [tag.tag_id for tag in session.query(Tag).all()]

    def get_tag_format_ids(self) -> list[int]:
        """
        TAG_FORMATSテーブルからすべてのフォーマットIDを取得する
        Returns:
            list[int]: すべてのフォーマットIDのリスト。
        """
        with self.session_factory() as session:
            return [format.format_id for format in session.query(TagFormat).all()]

    def get_tag_languages(self) -> list[str]:
        """
        TAG_TRANSLATIONSテーブルからすべての言語を取得する
        Returns:
            list[str]: すべての言語のリスト。
        """
        with self.session_factory() as session:
            return [translation.language for translation in session.query(TagTranslation).all()]

    def get_tag_types(self, format_id: int) -> list[str]:
        """
        TAG_TYPE_NAMEテーブルから指定フォーマットのすべてのタイプを取得する

        Args:
            format_id (int): フォーマットID

        Returns:
            list[str]: すべてのタイプのリスト。
        """
        with self.session_factory() as session:
            rows = (
                session.query(TagTypeName.type_name)
                .join(
                    TagTypeFormatMapping,
                    TagTypeName.type_name_id == TagTypeFormatMapping.type_name_id
                )
                .filter(TagTypeFormatMapping.format_id == format_id)
                .all()
            )
            # rows は [("Animal",), ("Character",), ...] のように
            # 「単一カラムをタプルにしたリスト」が返る。

        # タプルから文字列だけ取り出して返す
        return [row[0] for row in rows]
