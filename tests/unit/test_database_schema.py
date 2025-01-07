import pytest
from unittest.mock import Mock, patch
from sqlalchemy import inspect, create_engine, StaticPool
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError

# --- テスト対象のクラス・モデルをインポート ---
from genai_tag_db_tools.data.database_schema import (
    Tag, TagFormat, TagTranslation, TagStatus, TagTypeName, TagTypeFormatMapping
)
from genai_tag_db_tools.data.database_schema import Base  # Baseはmetadata.create_all()用
from genai_tag_db_tools.db.database_setup import engine as global_engine, SessionLocal as GlobalSessionLocal
from genai_tag_db_tools.data.database_schema import TagDatabase

# =============================================================================
# フィクスチャ定義: テスト用のメモリDBエンジンとセッション
# =============================================================================

@pytest.fixture(scope="function")
def memory_engine():
    """
    テスト用に毎回新しい in-memory SQLite エンジンを作成し返すフィクスチャ。
    """
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    yield test_engine
    # teardownは不要: :memory: のためテスト終了後に消える

@pytest.fixture(scope="function")
def db_session(memory_engine) -> Session:
    """
    テスト用のSessionLocalを作成し、呼び出し元で使用するセッションを返す。
    """
    TestSessionLocal = sessionmaker(bind=memory_engine)
    session = TestSessionLocal()
    yield session
    # teardown
    session.close()

@pytest.fixture(scope="function")
def tag_database_test(db_session, memory_engine):
    """
    テスト用データベースへ接続した TagDatabase インスタンスを返すフィクスチャ。
    新実装の TagDatabase は「external_session と init_master」を受け取る。
    ここでは外部セッションを注入し、マスターデータ初期化前にテーブル作成を明示的に実行。
    """
    # 1) テーブル作成 (Base.metadata.create_all)
    Base.metadata.create_all(memory_engine)

    # 2) TagDatabaseインスタンスを作成（外部セッションを注入）
    #    init_master=True にすると create_tables + init_master_data が呼ばれますが、
    #    ここではすでにテーブルをcreate_all()しているので、好みに応じてFalseに。
    db = TagDatabase(external_session=db_session, init_master=True)

    return db

# =============================================================================
# テスト群
# =============================================================================

def test_tagdatabase_initialization(tag_database_test):
    db = tag_database_test
    assert db.engine is not None
    assert db.session is not None

def test_create_tables(tag_database_test, memory_engine):
    """ 必要なテーブルが作成されているのかの確認 """
    db = tag_database_test

    # SQLAlchemyのインスペクター(Inspector)でテーブル一覧を取得
    inspector = inspect(memory_engine)

    # create_tables() を呼び直し → 既にあるが呼んでもエラーなく動くはず
    db.create_tables()
    tables = inspector.get_table_names()
    expected_tables = [
        "TAGS",
        "TAG_TRANSLATIONS",
        "TAG_FORMATS",
        "TAG_TYPE_NAME",
        "TAG_TYPE_FORMAT_MAPPING",
        "TAG_STATUS",
        "TAG_USAGE_COUNTS",
    ]
    for table in expected_tables:
        assert table in tables

def test_init_master_data(tag_database_test):
    """ Tag Format のマスターデータが初期化されているかの確認 """
    db = tag_database_test
    session = db.session

    # init_master_data() が走っている想定。実際にTagFormatをクエリして確認する。
    formats = session.query(TagFormat).all()
    # デフォルト初期化で4件 (unknown, danbooru, e621, derpibooru) が入るはず
    # すでにデータがあればスキップする実装の場合、ここで件数が4以上になっているかも
    assert len(formats) >= 4

    # とくに "unknown", "danbooru", "e621", "derpibooru" が含まれているか確認
    format_names = [f.format_name for f in formats]
    assert "unknown" in format_names
    assert "danbooru" in format_names
    assert "e621" in format_names
    assert "derpibooru" in format_names

def test_insert_tag(tag_database_test):
    """ タグが正しく挿入されるかの確認 """
    db = tag_database_test
    session = db.session

    new_tag = Tag(tag_id=1, source_tag="source_tag", tag="test_tag")
    session.add(new_tag)
    session.commit()

    retrieved_tag = session.query(Tag).filter_by(tag_id=1).one()
    assert retrieved_tag.tag == "test_tag"
    assert retrieved_tag.source_tag == "source_tag"

def test_tag_translations(tag_database_test):
    db = tag_database_test
    session = db.session

    new_tag = Tag(tag_id=1, source_tag="source_tag", tag="test_tag")
    session.add(new_tag)
    session.commit()

    translation = TagTranslation(
        translation_id=1,
        tag_id=1,
        language="en",
        translation="translated_tag",
    )
    session.add(translation)
    session.commit()

    retrieved_tag = session.query(Tag).filter_by(tag_id=1).one()
    assert len(retrieved_tag.translations) == 1
    assert retrieved_tag.translations[0].language == "en"
    assert retrieved_tag.translations[0].translation == "translated_tag"

def test_cleanup(tag_database_test):
    """
    cleanup メソッドがセッションを正しく管理するかテスト
    (SQLAlchemyの仕様上、close()後にis_activeがFalseになると限らないので、
    セッションが_tagDatabaseから除外されたかどうかを確認する)
    """
    db = tag_database_test
    session = db.session

    # 念のため外部セッションも_ sessionsに登録
    if session not in db._sessions:
        db._sessions.add(session)

    # 実行前にセットに含まれていることを確認
    assert session in db._sessions

    # cleanup実行
    db.cleanup()

    # cleanup後、_sessions から除外されていることを確認
    assert session not in db._sessions

def test_tagdatabase_with_existing_session():
    """
    セッションが既にある場合の初期化を確認するテスト。

    - in-memory DBを作ってSessionを手動生成
    - TagDatabaseのコンストラクタへ external_session として渡す
    - TagDatabase がそのセッションを用いているか確認
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    TestSessionLocal = sessionmaker(bind=engine)
    session = TestSessionLocal()

    # テーブル作成
    Base.metadata.create_all(engine)

    # TagDatabase の初期化
    db = TagDatabase(external_session=session, init_master=True)

    assert db.engine == engine
    assert db.session == session

    # 何かinsertテスト
    tag = Tag(tag_id=99, source_tag="src", tag="existing_session")
    session.add(tag)
    session.commit()

    # 取り出せるか
    retrieved = session.query(Tag).filter_by(tag_id=99).one()
    assert retrieved.tag == "existing_session"

def test_tagstatus_primarykey_violation(tag_database_test):
    """
    TagStatusテーブルの複合主キー(tag_id, format_id)が既に存在する状態で
    同じキーを挿入し、UniqueViolation(IntegrityError)が出るかを確認するテスト
    """
    db = tag_database_test
    session = db.session

    # 事前にTagを1件挿入
    new_tag = Tag(tag_id=1, source_tag="source_tag", tag="test_tag")
    session.add(new_tag)
    session.commit()

    # 1件目のTagStatusレコード
    status1 = TagStatus(
        tag_id=1,
        format_id=1,    # 'danbooru'想定
        type_id=0,      # general
        alias=False,
        preferred_tag_id=1,
    )
    session.add(status1)
    session.commit()

    # 2件目: 同じtag_id=1, format_id=1 → 重複キー
    status2 = TagStatus(
        tag_id=1,
        format_id=1,
        type_id=3,      # copyrightとか
        alias=False,
        preferred_tag_id=1
    )

    with pytest.raises(IntegrityError):
        session.add(status2)
        session.commit()

def test_tagstatus_checkconstraint_violation(tag_database_test):
    """
    TagStatusテーブルのCheckConstraint:
      (alias = false AND preferred_tag_id = tag_id) OR
      (alias = true AND preferred_tag_id != tag_id)
    を違反するレコードを挿入してエラーになることを確認
    """
    db = tag_database_test
    session = db.session

    # 事前にTagを2件挿入 (tag_id=1, tag_id=2)
    session.add_all([
        Tag(tag_id=1, source_tag="source1", tag="test_tag1"),
        Tag(tag_id=2, source_tag="source2", tag="test_tag2"),
    ])
    session.commit()

    # OK例: alias=False, preferred_tag_id=tag_id
    status_ok = TagStatus(
        tag_id=1,
        format_id=1,
        type_id=0,
        alias=False,
        preferred_tag_id=1
    )
    session.add(status_ok)
    session.commit()

    # 違反例: alias=False なのに preferred_tag_id != tag_id
    status_ng = TagStatus(
        tag_id=2,
        format_id=1,
        type_id=3,
        alias=False,
        preferred_tag_id=1
    )
    with pytest.raises(IntegrityError):
        session.add(status_ng)
        session.commit()
