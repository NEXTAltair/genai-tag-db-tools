.. _package_specification:

=======================================
パッケージ仕様: genai_tag_db_tools
=======================================

.. contents::
   :local:
   :depth: 2

概要
====
パッケージ ``genai_tag_db_tools`` は、タグデータベースを管理し、データのインポート、検索、クリーニング、翻訳、および統計を提供するためのツールセット。
以下は、ディレクトリ構造および主なモジュールの仕様。

ディレクトリ構造
================

.. code-block:: text

    genai_tag_db_tools/
        cleanup_str.py
        config.py
        core/
            db_maintenance_tool.py
            import_data.py
            processor.py
            tag_search.py
            __init__.py
        data/
            alembic.ini
            database_schema.py
            extracted_models.py
            tags_v4.db (binary file)
            tag_database_alembic/
                env.py
                README
                script.py.mako
            versions/
                tag_repository.py
            xml/
        gui/
            designer/
                MainWindow.ui
                MainWindow_ui.py
                ProgressWidget.ui
                ProgressWidget_ui.py
                TagCleanerWidget.ui
                TagCleanerWidget_ui.py
                TagDataImportDialog.ui
                TagDataImportDialog_ui.py
                TagRegisterWidget.ui
                TagRegisterWidget_ui.py
                TagSearchWidget.ui
                TagSearchWidget_ui.py
                TagStatisticsWidget.ui
                TagStatisticsWidget_ui.py
                __init__.py
            widgets/
                tag_cleaner.py
                tag_import.py
                tag_register.py
                tag_search.py
                tag_statistics.py
                __init__.py
            windows/
                00.py
                main_window.py
                __init__.py
        main.py
        utils/
            __init__.py

主要コンポーネント
==================

``cleanup_str.py``
-------------------
タグのクリーニングと正規化を行うユーティリティ。
`kohya-ss/sd-scripts <https://github.com/kohya-ss/sd-scripts>`_ より大部分を移植

主なクラスと関数:

- ``TagCleaner``

  - タグのクリーニングロジックをカプセル化。

  例えば、より具体的なタグへの統合。

  入力例:

  .. code-block:: text

    long hair, blue eyes, hair

  出力例:

  .. code-block:: text

    long hair, blue eyes

  - 複数の人物がいる場合､髪型や目の色などの要素の混ざりやすい情報を削除。

  - タグを正規化。

  .. code-block:: python

    clean_tags(text: str) -> str

``config.py``
-------------
データベース接続や全体設定を定義。

- ``db_path``: SQLiteデータベースファイルのパス。
- ``AVAILABLE_COLUMNS``: タグデータにおけるカラム情報を定義。

``core`` ディレクトリ
---------------------

**``db_maintenance_tool.py``**

データベースのメンテナンス機能を提供。

- ``detect_duplicates_in_tag_status() -> list[dict]``:

  - 重複するタグステータスレコードを検出。

- ``optimize_indexes()``:

  - データベースインデックスの再構築。

**``import_data.py``**

データインポートロジックを管理。

- ``TagDataImporter``

  - ``read_csv(csv_file_path: Path) -> pl.DataFrame``:

    - CSVファイルからデータを読み込み。

      データはカンマ区切りで、以下のカラムを含むことが推奨。

      .. list-table:: 推奨カラム構成
         :header-rows: 1

         * - ``source_tag``
           - 元のタグ。
         * - ``translation``
           - 翻訳文字列。
         * - ``count``
           - タグの使用頻度。

  - ``configure_import(source_df: pl.DataFrame) -> tuple[pl.DataFrame, ImportConfig]``:

    - データのインポート設定を定義。
    - カラムのマッピングや言語設定を柔軟に調整可能。

**``processor.py``**

CSVファイルをデータベースに変換し、挿入するロジックを含む。
  - CSVの行ごとにIDを生成し、適切な正規化とデータ挿入を行う。

**``tag_search.py``**

--------------------

**``database_schema.py``**

SQLAlchemyを使用してデータベーススキーマを定義。

詳細なスキーマ設計については :doc:`database_design` を参照。

- ``Tag``
  - タグ情報を管理。

- ``TagTranslation``
  - タグの翻訳を格納。

**``tag_repository.py``**

データベースとのインターフェースを提供。

``gui`` ディレクトリ
---------------------

GUI関連のコードを含むディレクトリ。

**``designer`` サブディレクトリ**

Qt Designerで作成されたUIファイル。人力修正は不要

**``widgets`` サブディレクトリ**

GUIウィジェットのロジックを実装。

使用例
======
タグ検索
--------

.. code-block:: python

    from genai_tag_db_tools.core.tag_search import TagSearcher

    searcher = TagSearcher()
    results = searcher.search_tags("1boy")
    print(results)

データインポート
----------------

.. code-block:: python

    from genai_tag_db_tools.core.import_data import TagDataImporter

    importer = TagDataImporter()
    importer.import_data("path/to/csv")

カスタム設定
============

必要に応じて、プロジェクトに合わせて以下の設定を調整：

- ``config.py``: データベースパスやカラム設定。
- ``conf.py``: Sphinx用のドキュメント設定。
