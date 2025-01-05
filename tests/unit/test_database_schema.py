import pytest
from unittest.mock import Mock, patch
from sqlalchemy import inspect, create_engine, StaticPool
from sqlalchemy.orm import sessionmaker, Session
from genai_tag_db_tools.data.database_schema import (
    TagDatabase,
    Tag,
    TagFormat,
    TagTranslation,
    TagStatus
)

@pytest.fixture(scope="function")
def tag_database_test(engine, db_session):
    """テスト用データベースへ接続した TagDatabase インスタンスを返す"""
    db = TagDatabase(engine=engine, session=db_session, init_master=False)

    db.create_tables()
    db.init_master_data()
    return db

def test_tagdatabase_initialization(tag_database_test):
    db = tag_database_test
    assert db.engine is not None
    assert db.session is not None

def test_create_tables(tag_database_test):
    """ 必要なテーブルが作成されているのかの確認 """

    db = tag_database_test

    # SQLAlchemyのインスペクター(Inspector)は、データベースのスキーマ情報を取得する
    inspector = inspect(db.engine)

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

    # TagFormatのモックオブジェクトを作成
    mock_formats = []
    format_data = [
        {"format_id": 0, "format_name": "unknown"},
        {"format_id": 1, "format_name": "danbooru"},
        {"format_id": 2, "format_name": "e621"},
        {"format_id": 3, "format_name": "derpibooru"}
    ]

    for data in format_data:
        mock_format = Mock(spec=TagFormat)  # TagFormatの仕様に基づくモック
        mock_format.format_id = data["format_id"]
        mock_format.format_name = data["format_name"]
        mock_formats.append(mock_format)

    mock_query = Mock()
    mock_query.all.return_value = mock_formats  # all()の戻り値を設定

    # db.sessionのqueryメソッドを置き換え
    with patch.object(db.session, 'query', return_value=mock_query):
        tag_formats = db.session.query(TagFormat).all()
        assert len(tag_formats) == 4
        assert tag_formats[0].format_name == "unknown"
        assert tag_formats[1].format_name == "danbooru"
        assert tag_formats[2].format_name == "e621"
        assert tag_formats[3].format_name == "derpibooru"

def test_insert_tag(tag_database_test):
    """ タグが正しく挿入されるかの確認 """
    db = tag_database_test
    session = db.session
    new_tag = Tag(tag_id=1, source_tag="source_tag", tag="test_tag")
    session.add(new_tag)
    session.commit()
    retrieved_tag = session.query(Tag).filter_by(tag_id=1).one()
    assert retrieved_tag.tag == "test_tag"

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
    assert retrieved_tag.translations[0].translation == "translated_tag"

def test_cleanup(tag_database_test):
    """cleanup メソッドがセッションを正しくクローズするかテスト"""
    db = tag_database_test

    # テスト用のセッションを作成し、db._sessions に追加
    session = db.create_session()
    db._sessions.add(session)

    print(f"Test session created: {session}, ID: {id(session)}")  # セッションオブジェクトのIDを確認

    # cleanup 前の状態確認
    print(f"Before cleanup: Session active - {session.is_active}")
    assert session.is_active

    # cleanup 実行
    db.cleanup()

    # cleanup 後の状態確認
    print(f"After cleanup: Session active - {session.is_active}")

    # セッションがクローズされたことを確認するために、データベース操作を試みる
    try:
        session.query(Tag).all()
        assert False, "セッションはクローズされているはずです"
    except Exception as e:
        print(f"Expected exception: {e}")
        assert True

def test_tagdatabase_with_existing_engine(tag_database_test):
    """エンジンが既にある場合の初期化を確認するテスト"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=True,
    )
    db = tag_database_test
    db.engine = engine
    db.create_tables()
    db.init_master_data()
    assert db.engine == engine
    assert db.session is not None

def test_tagdatabase_with_existing_session(tag_database_test):
    """セッションが既にある場合の初期化を確認するテスト"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=True,
    )
    db = tag_database_test
    db.engine = engine

    # sessionmaker() でローカルな Session クラスを定義
    SessionLocal = sessionmaker(bind=engine)

    # ここで session を作成
    session = SessionLocal()

    # TagDatabase のコンストラクタ引数に session を渡す
    db = TagDatabase(session=session, init_master=True)

    assert db.engine == session.get_bind()
    assert db.session == session

def test_tagstatus_primarykey_violation(tag_database_test):
    """
    TagStatusテーブルの複合主キー(tag_id, format_id)が既に存在する状態で
    さらに同じキーを挿入しようとしてUniqueViolation(IntegrityError)が出るかを確認するテスト
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
        format_id=1,    # 例えば 'danbooru'
        type_id=0,      # general
        alias=False,
        preferred_tag_id=1,
    )
    session.add(status1)
    session.commit()

    # 2件目: 同じtag_id=1, format_id=1を意図的に再度挿入し、IntegrityErrorが発生するか確認
    status2 = TagStatus(
        tag_id=1,
        format_id=1,
        type_id=3,
        alias=False,
        preferred_tag_id=1
    )

    from sqlalchemy.exc import IntegrityError
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

    # 普通に挿入: alias=False, preferred_tag_id=tag_id => OK
    status_ok = TagStatus(
        tag_id=1,
        format_id=1,
        type_id=0,
        alias=False,
        preferred_tag_id=1  # same as tag_id => valid
    )
    session.add(status_ok)
    session.commit()

    # 違反ケース: alias=Falseなのにpreferred_tag_id != tag_id => CheckConstraint違反
    status_ng = TagStatus(
        tag_id=2,
        format_id=1,
        type_id=3,
        alias=False,
        preferred_tag_id=1  # ここを2ではなく1にすると矛盾が生じる
    )
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        session.add(status_ng)
        session.commit()
