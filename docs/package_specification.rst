.. _package_specification:

パッケージ仕様: genai_tag_db_tools
===============================

.. contents::
   :local:
   :depth: 2

概要
====

パッケージ ``genai_tag_db_tools`` は、タグデータベースを管理し、データのインポート、検索、クリーニング、翻訳、および統計を提供するためのツールセット。
以下は、ディレクトリ構造および主なモジュールの仕様。

依存関係
=======

必須パッケージ
============

.. code-block:: text

    PySide6>=6.5.2         # GUIフレームワーク
    SQLAlchemy>=2.0.0      # ORMとデータベース操作
    alembic>=1.12.0        # データベースマイグレーション
    polars>=0.19.12        # データ処理と分析
    pyyaml>=6.0.1         # 設定ファイルの読み込み
    loguru>=0.7.2         # ロギング
    typing-extensions>=4.8.0  # 型ヒント拡張

開発用パッケージ
=============

.. code-block:: text

    pytest>=7.4.2         # テストフレームワーク
    pytest-cov>=4.1.0     # カバレッジレポート
    black>=23.9.1         # コードフォーマッター
    ruff>=0.0.291        # リンター
    mypy>=1.5.1          # 静的型チェック
    sphinx>=7.2.6        # ドキュメント生成

モジュール構成
===========

core
----

基本機能を提供するコアモジュール群。

**tag_manager.py**

.. code-block:: python

    class TagManager:
        """タグ管理の中核機能を提供するクラス
        
        このクラスは以下の機能を提供します:
        - タグの登録・更新
        - タグの検索
        - 翻訳の管理
        - 使用統計の追跡
        """
        
        def register_tag(self, tag_data: TagData) -> Tag:
            """新しいタグを登録
            
            Args:
                tag_data (TagData): タグ情報を含むデータクラス
                
            Returns:
                Tag: 登録されたタグオブジェクト
                
            Raises:
                DuplicateTagError: タグが既に存在する場合
                ValidationError: タグデータが不正な場合
            """
            
        def search_tags(
            self, 
            query: str, 
            language: Optional[str] = None
        ) -> List[Tag]:
            """タグを検索
            
            Args:
                query (str): 検索クエリ
                language (Optional[str]): 検索対象の言語
                
            Returns:
                List[Tag]: 検索結果のタグリスト
            """

**database.py**

データベース接続とセッション管理を提供。

.. code-block:: python

    def get_session() -> Session:
        """データベースセッションを取得
        
        Returns:
            Session: SQLAlchemyセッションオブジェクト
            
        Raises:
            DatabaseConnectionError: DB接続に失敗した場合
        """

services
--------

ビジネスロジックを実装するサービス層。

**tag_service.py**

.. code-block:: python

    class TagService:
        """タグ関連のビジネスロジックを提供
        
        以下の機能を実装:
        - タグのバリデーション
        - 重複チェック
        - 正規化処理
        """

**translation_service.py**

.. code-block:: python

    class TranslationService:
        """翻訳関連の機能を提供
        
        - 翻訳の追加・更新
        - 言語間の変換
        - 翻訳品質の検証
        """

エラー定義
========

**exceptions.py**

.. code-block:: python

    class TagError(Exception):
        """タグ関連の基底例外クラス"""
        
    class DuplicateTagError(TagError):
        """タグ重複時の例外"""
        
    class ValidationError(TagError):
        """バリデーション失敗時の例外"""
        
    class DatabaseError(Exception):
        """データベース操作の基底例外クラス"""
        
    class DatabaseConnectionError(DatabaseError):
        """DB接続失敗時の例外"""

エラーハンドリング
==============

1. 例外の階層構造
   - 基底例外クラスから派生
   - 具体的なエラー状況を示す例外クラス
   - エラーメッセージの多言語対応

2. エラーログ
   - エラーレベルに応じたログ出力
   - スタックトレースの保存
   - エラー発生時の状態情報の記録

3. GUI表示
   - ユーザーフレンドリーなエラーメッセージ
   - エラー状況に応じた対処方法の提示
   - デバッグモードでの詳細情報表示

設定ファイル
=========

**config.yaml**

.. code-block:: yaml

    database:
      path: data/tags_v4.db
      pool_size: 5
      max_overflow: 10
      echo: false  # SQLログ出力の有無
      
    logging:
      level: INFO
      file: logs/app.log
      format: "{time} {level} {message}"
      rotation: "1 week"
      
    gui:
      theme: light
      language: ja
      window:
        width: 800
        height: 600
      
    performance:
      cache_size: 1000
      batch_size: 100
      
    development:
      debug: false
      mock_translation: false

設定項目の説明
===========

1. database
   - path: データベースファイルのパス
   - pool_size: コネクションプールのサイズ
   - max_overflow: 最大超過接続数
   - echo: SQLログ出力の有無

2. logging
   - level: ログレベル (DEBUG/INFO/WARNING/ERROR)
   - file: ログファイルのパス
   - format: ログのフォーマット
   - rotation: ログローテーション設定

3. gui
   - theme: GUIテーマ (light/dark)
   - language: 表示言語
   - window: ウィンドウサイズ設定

4. performance
   - cache_size: キャッシュサイズ
   - batch_size: バッチ処理のサイズ

5. development
   - debug: デバッグモードの有無
   - mock_translation: 翻訳機能のモック化

型定義
=====

**types.py**

.. code-block:: python

    from dataclasses import dataclass
    from datetime import datetime
    from typing import Dict, List, Optional

    @dataclass
    class TagData:
        """タグデータを表現するデータクラス"""
        source_tag: str
        translations: Dict[str, str]
        count: Optional[int] = 0
        created_at: datetime = field(default_factory=datetime.now)
        
    @dataclass
    class TranslationData:
        """翻訳データを表現するデータクラス"""
        text: str
        language: str
        confidence: float
        
    @dataclass
    class SearchResult:
        """検索結果を表現するデータクラス"""
        tags: List[TagData]
        total_count: int
        page: int
        per_page: int

使用例
=====

1. 基本的な使用方法

.. code-block:: python

    from genai_tag_db_tools import TagManager
    
    # マネージャーの初期化
    manager = TagManager()
    
    # タグの検索
    results = manager.search_tags("landscape")
    
    # タグの登録
    tag_data = TagData(
        source_tag="new_tag",
        translations={"ja": "新しいタグ"}
    )
    manager.register_tag(tag_data)

2. エラーハンドリング

.. code-block:: python

    from genai_tag_db_tools.exceptions import DuplicateTagError
    
    try:
        manager.register_tag(tag_data)
    except DuplicateTagError as e:
        logger.error(f"タグ重複エラー: {e}")
        # エラー処理
    except ValidationError as e:
        logger.error(f"バリデーションエラー: {e}")
        # エラー処理

3. バッチ処理

.. code-block:: python

    # 複数タグの一括登録
    tags_data = [
        TagData(source_tag="tag1", translations={"ja": "タグ1"}),
        TagData(source_tag="tag2", translations={"ja": "タグ2"}),
    ]
    
    manager.bulk_register_tags(tags_data)

4. 設定のカスタマイズ

.. code-block:: python

    from genai_tag_db_tools.config import Config
    
    # 設定の読み込み
    config = Config.load("custom_config.yaml")
    
    # カスタム設定でマネージャーを初期化
    manager = TagManager(config=config)
