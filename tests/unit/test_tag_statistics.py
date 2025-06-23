# tests.unit.test_tag_statistics
import polars as pl
import pytest

# 2) テストで使用する DB セッション関連クラスをインポート
from genai_tag_db_tools.data.database_schema import TagDatabase

# 1) テスト対象のクラスをインポート
from genai_tag_db_tools.services.tag_statistics import TagStatistics


@pytest.fixture(scope="function")
def tag_statistics(db_session):
    """
    テスト用の TagStatistics インスタンスを返すフィクスチャ。
    DBをセットアップし、必要なら初期データを挿入してから返します。

    scope="module":
      - このフィクスチャはモジュール(ファイル)内のテスト間で使い回される設定
      - テスト毎にDBをリセットしたい場合は scope="function" にするか、設計を工夫します
    """
    # 1) InMemoryやテスト用DBで TagDatabase を初期化する例
    # 外部セッションを注入し、テーブル作成やマスタ初期化を行う
    tag_db = TagDatabase(external_session=db_session, init_master=True)

    # 2) テストデータの投入（必要な場合）
    #    TagDatabase のメソッドまたは TagRepository 経由で追加が可能です。
    #    ここではサンプルとして数件のタグ＆使用回数などを入れてみます。
    #    すでに init_master_data() により TagFormat / TagTypeName / TagTypeFormatMapping
    #    あたりは初期化されている想定。
    stats = TagStatistics(session=db_session)  # セッションを正しく渡す
    repo = stats.repo  # TagStatisticsの内部で生成されるTagRepositoryを取得

    # サンプルタグを作成
    tag_id_dog = repo.create_tag(source_tag="dog", tag="dog")
    tag_id_cat = repo.create_tag(source_tag="cat", tag="cat")

    # フォーマットIDを取得 (例: danbooru=1, e621=2 など)
    format_danbooru_id = repo.get_format_id("danbooru")
    format_e621_id = repo.get_format_id("e621")

    # 使用回数を更新
    repo.update_usage_count(tag_id_dog, format_danbooru_id, 10)
    repo.update_usage_count(tag_id_dog, format_e621_id, 5)
    repo.update_usage_count(tag_id_cat, format_danbooru_id, 0)
    repo.update_usage_count(tag_id_cat, format_e621_id, 2)

    # エイリアス設定 (例: cat を e621 フォーマットで alias=True にする)
    #   preferred_tag_id を既存の同じ tag_id にしておかないと制約違反になる場合があります。
    #   alias=True の場合は別タグを preferred_tag にする設計など、要件次第。
    try:
        repo.update_tag_status(
            tag_id=tag_id_cat,
            format_id=format_e621_id,
            alias=True,
            preferred_tag_id=tag_id_dog,
            type_id=0,  # e621のgeneralタイプを使用
        )
    except ValueError:
        # alias=False で再設定 (エイリアス設定のバリデーションが通らない場合の例)
        repo.update_tag_status(
            tag_id=tag_id_cat,
            format_id=format_e621_id,
            alias=False,
            preferred_tag_id=tag_id_cat,
            type_id=0,  # e621のgeneralタイプを使用
        )

    # 翻訳を追加 (dog: 英語=dog, 日本語=犬, cat: 英語=cat, 日本語=猫)
    repo.add_or_update_translation(tag_id_dog, "en", "dog")
    repo.add_or_update_translation(tag_id_dog, "ja", "犬")
    repo.add_or_update_translation(tag_id_cat, "en", "cat")
    repo.add_or_update_translation(tag_id_cat, "ja", "猫")

    # 3) テスト対象の TagStatistics インスタンスを返す
    yield stats

    # 4) テスト終了後のクリーンアップ
    #    (InMemoryの場合は特に不要かもしれませんが、DBセッションのクローズなど)
    tag_db.cleanup()


def test_general_stats(tag_statistics):
    """
    全体的なサマリ (総タグ数 / aliasタグ数 / non-aliasタグ数) をテスト
    """
    result = tag_statistics.get_general_stats()
    assert "total_tags" in result
    assert "alias_tags" in result
    assert "non_alias_tags" in result

    # サンプルで登録した2件のタグ + init_master_data()の内部で追加されたタグ数等により
    # テスト環境次第で数値が変わるため、ここでは大まかな正当性チェックのみ
    assert result["total_tags"] >= 2
    assert result["alias_tags"] >= 0
    assert result["non_alias_tags"] >= 0
    assert result["alias_tags"] + result["non_alias_tags"] == result["total_tags"]


def test_usage_stats(tag_statistics):
    """
    get_usage_stats() の結果が Polars DataFrame であり、
    サンプルで設定した使用回数が反映されているかをテスト
    """
    df = tag_statistics.get_usage_stats()
    assert isinstance(df, pl.DataFrame)

    # dog, cat で usage_count を設定
    # dog: danbooru=10, e621=5
    # cat: danbooru=0, e621=2
    # というデータが返ってくるかどうか (存在しないフォーマットや初期タグがあるかもしれないので一部だけ確認)

    # 行のうち、tag_id が dog, format_name=danbooru の usage_count を確認
    # まずはdog/catのtag_idを取得
    repo = tag_statistics.repo
    dog_id = repo.get_tag_id_by_name("dog", partial=False)
    cat_id = repo.get_tag_id_by_name("cat", partial=False)

    # dog(danbooru) = 10
    # フォーマット名からフィルタ
    subset_dog_danbooru = df.filter((pl.col("tag_id") == dog_id) & (pl.col("format_name") == "danbooru"))
    assert len(subset_dog_danbooru) == 1
    assert subset_dog_danbooru[0, "usage_count"] == 10

    # cat(e621) = 2
    subset_cat_e621 = df.filter((pl.col("tag_id") == cat_id) & (pl.col("format_name") == "e621"))
    assert len(subset_cat_e621) == 1
    assert subset_cat_e621[0, "usage_count"] == 2


def test_type_distribution(tag_statistics):
    """
    タイプ分布 (format_id, type_name 別のタグ数) のテスト
    """
    df = tag_statistics.get_type_distribution()
    assert isinstance(df, pl.DataFrame)
    # 例: カラム "format_name", "type_name", "tag_count"
    assert set(df.columns) == {"format_name", "type_name", "tag_count"}

    # タグ数が 0 のレコードも含まれている可能性はあるが、
    # 少なくともフォーマット("danbooru","e621"等)の行が存在するはず
    assert len(df) > 0

    # 一例として、"danbooru" のいくつかの type_name で tag_count が >= 0 であることを確認
    # (テストデータによって変わるため、厳密な値はチェックしない)
    subset_danbooru = df.filter(pl.col("format_name") == "danbooru")
    assert len(subset_danbooru) > 0
    for row in subset_danbooru.iter_rows(named=True):
        assert row["tag_count"] >= 0


def test_translation_stats(tag_statistics):
    """
    翻訳情報の統計のテスト
    """
    df = tag_statistics.get_translation_stats()
    assert isinstance(df, pl.DataFrame)
    assert set(df.columns) == {"tag_id", "total_translations", "languages"}

    # サンプルで "dog" に英語(en)と日本語(ja) を登録したので total_translations=2 になっているはず
    repo = tag_statistics.repo
    dog_id = repo.get_tag_id_by_name("dog", partial=False)
    row_dog = df.filter(pl.col("tag_id") == dog_id)
    assert len(row_dog) == 1
    assert row_dog[0, "total_translations"] == 2
    assert set(row_dog[0, "languages"]) == {"en", "ja"}
