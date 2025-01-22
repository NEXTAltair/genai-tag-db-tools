.. _dev_guide:

Developer Guide (開発者向けガイド)
================================

このガイドでは、``genai-tag-db-tools`` の開発に必要な情報を提供します。

アーキテクチャ概要
================

システムは以下の3層で構成されています：

1. **データ層 (Data Layer)**
   
   SQLiteデータベースを用いたタグ情報の永続化層。

   - 主要テーブル構成:
     * TAGS: 基本的なタグ情報
     * TAG_TRANSLATIONS: 翻訳情報
     * TAG_USAGE_COUNTS: 使用頻度情報
   
   .. code-block:: python

       from sqlalchemy import create_engine, Column, Integer, String
       from sqlalchemy.ext.declarative import declarative_base

       Base = declarative_base()

       class Tag(Base):
           __tablename__ = 'tags'
           
           tag_id = Column(Integer, primary_key=True)
           source_tag = Column(String)
           tag = Column(String, unique=True, nullable=False)

2. **ビジネスロジック層 (Business Logic Layer)**

   タグ操作の中核ロジックを提供。

   .. code-block:: python

       class TagService:
           def __init__(self, session):
               self.session = session
           
           def register_tag(self, tag_data):
               """タグを登録する

               Args:
                   tag_data (dict): タグ情報
                       - source_tag: 元のタグ文字列
                       - translations: 翻訳情報の辞書
                       
               Returns:
                   Tag: 登録されたタグオブジェクト
                   
               Raises:
                   DuplicateTagError: タグが既に存在する場合
               """
               try:
                   tag = Tag(
                       source_tag=tag_data['source_tag'],
                       tag=self._normalize_tag(tag_data['source_tag'])
                   )
                   self.session.add(tag)
                   self.session.commit()
                   return tag
               except IntegrityError:
                   raise DuplicateTagError(f"Tag {tag_data['source_tag']} already exists")

3. **インターフェース層 (Interface Layer)**

   PySide6ベースのGUIとPythonパッケージインターフェースを提供。

開発環境のセットアップ
====================

1. 前提条件
   - Python 3.12+
   - Git
   - Visual Studio Code (推奨)

2. リポジトリのクローンと環境構築:

   .. code-block:: bash

       git clone https://github.com/NEXTAltair/genai-tag-db-tools.git
       cd genai-tag-db-tools
       python -m venv venv
       venv\Scripts\activate  # Windowsの場合
       pip install -e ".[dev]"

3. VSCode拡張機能のインストール:
   - Python
   - Python Test Explorer
   - reStructuredText

コーディング規約
=============

1. PEP 8に準拠
   - インデント: 4スペース
   - 最大行長: 88文字 (blackの設定に合わせる)
   - クラス名: UpperCamelCase
   - 関数/変数名: snake_case

2. Docstring (Googleスタイル)

   .. code-block:: python

       def process_tag(tag: str, language: str = "en") -> Dict[str, Any]:
           """タグを処理し、正規化と翻訳を行う

           Args:
               tag (str): 処理対象のタグ文字列
               language (str, optional): 翻訳先言語. デフォルトは "en"

           Returns:
               Dict[str, Any]: 処理結果
                   - normalized_tag (str): 正規化されたタグ
                   - translation (str): 翻訳結果
                   - confidence (float): 翻訳の信頼度

           Raises:
               ValueError: タグが空文字列の場合
           """

テストの書き方
===========

1. 基本的なテスト構造

   .. code-block:: python

       import pytest
       from genai_tag_db_tools.services.tag_service import TagService

       @pytest.fixture
       def tag_service():
           """TagServiceのフィクスチャ"""
           return TagService()

       def test_normalize_tag():
           """タグ正規化のテスト"""
           service = tag_service()
           
           # 基本的なケース
           assert service.normalize_tag("test tag") == "test_tag"
           
           # 特殊文字を含むケース
           assert service.normalize_tag("test(tag)") == "test\\(tag\\)"

2. モック使用例

   .. code-block:: python

       from unittest.mock import Mock, patch

       def test_tag_translation():
           """翻訳機能のテスト"""
           with patch('genai_tag_db_tools.services.translator.translate') as mock_translate:
               mock_translate.return_value = "テスト"
               
               service = TagService()
               result = service.translate_tag("test", target_lang="ja")
               
               assert result == "テスト"
               mock_translate.assert_called_once_with("test", "ja")

3. パラメータ化テスト

   .. code-block:: python

       @pytest.mark.parametrize("input_tag,expected", [
           ("test tag", "test_tag"),
           ("Test Tag", "test_tag"),
           ("test  tag", "test_tag"),
       ])
       def test_normalize_tag_variations(input_tag, expected):
           service = TagService()
           assert service.normalize_tag(input_tag) == expected

CI/CD設定
========

1. GitHub Actions設定 (.github/workflows/ci.yml)

   .. code-block:: yaml

       name: CI

       on: [push, pull_request]

       jobs:
         test:
           runs-on: windows-latest
           
           steps:
           - uses: actions/checkout@v2
           
           - name: Set up Python
             uses: actions/setup-python@v2
             with:
               python-version: '3.12'
           
           - name: Install dependencies
             run: |
               python -m pip install --upgrade pip
               pip install -e ".[dev]"
           
           - name: Run tests
             run: |
               pytest tests --cov=genai_tag_db_tools
           
           - name: Upload coverage
             uses: codecov/codecov-action@v2

2. リリース自動化 (.github/workflows/release.yml)

   .. code-block:: yaml

       name: Release

       on:
         push:
           tags:
             - 'v*'

       jobs:
         build:
           runs-on: windows-latest
           
           steps:
           - uses: actions/checkout@v2
           
           - name: Build and publish
             env:
               TWINE_USERNAME: ${{ secrets.PYPI_USERNAME }}
               TWINE_PASSWORD: ${{ secrets.PYPI_PASSWORD }}
             run: |
               python -m pip install build twine
               python -m build
               twine upload dist/*

コントリビューションガイドライン
===========================

1. Issue作成
   - バグ報告: 再現手順、期待される動作、実際の動作を記載
   - 機能要望: 目的、具体的な実装案、期待される効果を記載

2. プルリクエスト
   - 1つのPRにつき1つの機能/修正
   - テストコードを含める
   - コーディング規約に従う
   - CIが通過することを確認

3. コミットメッセージ
   - 形式: `<type>: <description>`
   - type:
     * feat: 新機能
     * fix: バグ修正
     * docs: ドキュメント
     * style: フォーマット
     * refactor: リファクタリング
     * test: テスト
     * chore: その他

4. ブランチ戦略
   - main: リリースブランチ
   - develop: 開発ブランチ
   - feature/*: 機能追加
   - fix/*: バグ修正
   - docs/*: ドキュメント更新

トラブルシューティング
==================

1. 開発環境の問題

   - **症状**: venvが作成できない
     **解決**: Python 3.12が正しくインストールされているか確認
   
   - **症状**: PySide6のインポートエラー
     **解決**: ``pip install PySide6`` を実行

2. テストの問題

   - **症状**: テストが失敗する
     **解決**: 
     1. venv が有効か確認
     2. 依存関係が最新か確認
     3. テストデータベースが正しく設定されているか確認

3. データベースの問題

   - **症状**: マイグレーションエラー
     **解決**:
     1. alembicのバージョン履歴をリセット
     2. マイグレーションを再実行

パフォーマンスチューニング
======================

1. データベース最適化

   .. code-block:: python

       # インデックス作成
       CREATE INDEX idx_tags_name ON tags(tag);
       CREATE INDEX idx_translations_tag_id ON tag_translations(tag_id);

2. キャッシュ戦略

   .. code-block:: python

       from functools import lru_cache

       class TagService:
           @lru_cache(maxsize=1000)
           def get_tag_by_id(self, tag_id: int) -> Tag:
               return self.session.query(Tag).get(tag_id)

3. バッチ処理

   .. code-block:: python

       def bulk_insert_tags(self, tags: List[Dict]):
           self.session.bulk_insert_mappings(Tag, tags)
           self.session.commit()

セキュリティ考慮事項
=================

1. SQLインジェクション対策
   - パラメータ化クエリの使用
   - ユーザー入力の検証

2. ファイルパス検証
   - パス走査攻撃の防止
   - 適切なパーミッション設定

3. エラーメッセージ
   - 本番環境では詳細なエラーを非表示
   - ログへの適切な記録
