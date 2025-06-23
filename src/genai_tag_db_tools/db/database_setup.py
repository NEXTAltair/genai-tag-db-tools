import importlib.resources
import logging
from pathlib import Path

from sqlalchemy import StaticPool, create_engine, event
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


def get_database_path() -> Path:
    """
    パッケージ内のデータベースファイルへの適切なパスを取得する。

    パッケージがインストールされている場合とソースから実行している場合の
    両方に対応したパス解決を行う。

    Returns:
        Path: データベースファイルへの絶対パス

    Raises:
        FileNotFoundError: データベースファイルが見つからない場合
    """
    logger.debug("データベースファイルパス解決を開始")

    try:
        # Python 3.9以降の推奨方法：importlib.resources.files()を使用
        if hasattr(importlib.resources, "files"):
            logger.debug("importlib.resources.files()を使用してパス解決を試行")
            package_files = importlib.resources.files("genai_tag_db_tools.data")
            db_path = package_files / "tags_v4.db"

            # リソースが存在する場合、実際のファイルパスを取得
            if db_path.is_file():
                logger.debug(f"パッケージリソースでファイルを発見: {db_path}")
                # パケージがインストールされている場合のパス取得
                with importlib.resources.as_file(db_path) as file_path:
                    resolved_path = Path(file_path)
                    logger.info(f"データベースパス解決成功（パッケージリソース）: {resolved_path}")
                    return resolved_path

        # フォールバック：__file__を使用した相対パス解決
        logger.debug("__file__を使用したフォールバックパス解決を試行")
        current_file = Path(__file__)
        package_root = current_file.parent.parent  # db/ -> genai_tag_db_tools/
        db_path = package_root / "data" / "tags_v4.db"

        logger.debug(f"パッケージルートからのパスを確認: {db_path}")
        if db_path.exists():
            logger.info(f"データベースパス解決成功（パッケージルート）: {db_path}")
            return db_path

        # 最後の手段：現在の作業ディレクトリからの相対パス
        logger.debug("作業ディレクトリからのフォールバックパス解決を試行")
        fallback_path = Path("src/genai_tag_db_tools/data/tags_v4.db")
        logger.debug(f"フォールバックパスを確認: {fallback_path.absolute()}")
        if fallback_path.exists():
            resolved_path = fallback_path.absolute()
            logger.info(f"データベースパス解決成功（フォールバック）: {resolved_path}")
            return resolved_path

        # すべての試行が失敗した場合の詳細エラー
        error_msg = (
            f"データベースファイルが見つかりません。以下の場所を確認してください:\n"
            f"1. パッケージ内: {package_root / 'data' / 'tags_v4.db'}\n"
            f"2. 開発環境: {fallback_path.absolute()}\n"
            f"3. 現在の作業ディレクトリ: {Path.cwd()}"
        )
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    except Exception as e:
        # より詳細なエラー情報を提供
        current_file = Path(__file__)
        package_root = current_file.parent.parent
        expected_path = package_root / "data" / "tags_v4.db"

        error_msg = (
            f"データベースファイルパスの解決に失敗しました: {e}\n"
            f"予想されるパス: {expected_path.absolute()}\n"
            f"現在の作業ディレクトリ: {Path.cwd()}\n"
            f"現在のファイル位置: {current_file.absolute()}"
        )
        logger.error(error_msg)
        raise FileNotFoundError(error_msg) from e


# グローバル変数として db_path を定義
db_path = get_database_path()


def enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


engine = create_engine(
    f"sqlite:///{db_path.absolute()}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)

event.listen(engine, "connect", enable_foreign_keys)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session_factory():
    """
    コンテキストマネージャとして使いやすいように
    session_factoryを返すor with文で使える仕組みにする
    """
    return SessionLocal
