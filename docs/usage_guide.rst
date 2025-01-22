.. _usage_guide:

Usage Guide (機能ガイド)
======================

このガイドでは、``genai-tag-db-tools`` の基本的な機能と使用方法について説明します。

GUIの起動と基本操作
================

PySide6ベースのGUIを用いてタグの検索・登録を行うことができます。

.. code-block:: bash

    genai-tag-db-tools-gui

メイン画面の構成
=============

1. メニューバー
   - File: データベース操作、アプリケーション終了
   - Tools: タグクリーナー、統計情報表示
   - Help: バージョン情報、ヘルプ表示

2. タグ検索エリア
   - 検索フィールド: タグ名の一部を入力
   - フィルターオプション: 言語、タグタイプ等
   - 結果表示エリア: 検索結果をグリッド表示

3. タグ詳細エリア
   - タグ基本情報（ID、名前、作成日等）
   - 翻訳情報
   - 使用統計
   - エイリアス情報

基本的な使用方法
=============

タグの検索
========

1. 検索フィールドにタグ名の一部を入力
2. エンターキーを押すか検索ボタンをクリック
3. 結果が下部グリッドに表示
4. グリッドの列をクリックしてソート可能

.. code-block:: text

    例: "girl"で検索
    - 1girl
    - girl_in_bag
    - school_girl
    など関連タグが表示されます

タグの登録
========

1. 「Add Tag」ボタンをクリック
2. 登録ダイアログで以下の情報を入力:
   - タグ名（必須）
   - 翻訳（オプション）
   - エイリアス（オプション）
   - タグタイプ（オプション）
3. 「Save」ボタンで保存

.. note::
   タグ名は一意である必要があります。重複する場合はエラーが表示されます。

タグの編集
========

1. 検索結果グリッドからタグを選択
2. 「Edit」ボタンをクリック
3. 情報を更新
4. 「Save」ボタンで保存

タグクリーナーの使用
================

1. Tools → Tag Cleanerを選択
2. クリーニングしたいタグリストを入力
3. クリーニングオプションを選択:
   - 重複除去
   - 正規化
   - エイリアス置換
4. 「Clean」ボタンでクリーニング実行

エラー対処方法
===========

データベース接続エラー
==================

.. code-block:: text

    Error: Unable to connect to database

**解決方法:**

1. データベースファイルの存在を確認
2. ファイルのパーミッションを確認
3. データベースが破損していないか確認

重複タグエラー
===========

.. code-block:: text

    Error: Duplicate tag entry

**解決方法:**

1. 既存タグを検索
2. 必要に応じてエイリアスとして登録
3. 異なるタグ名を使用

SQLiteデータベースの直接操作
=======================

本ツールはSQLiteデータベースを内部的に用いてタグ情報を保存します。
以下はPythonコードから直接データベースを操作する例です。

基本的な操作
=========

.. code-block:: python

    from genai_tag_db_tools import TagDatabase

    # データベース接続
    db = TagDatabase("path_to_your_db.sqlite")

    # タグ検索
    tag_info = db.search_tag("landscape")
    print(tag_info)
    # => [{'tag': 'landscape', 'translation': '風景', 'aliases': [], 'count': 123}, ...]

    # タグ登録
    db.add_tag("new_tag", translation="新しいタグ", aliases=["nt"], count=1)

    # 翻訳情報の取得
    translations = db.get_translations("landscape")
    print(translations)
    # => {'ja': '風景', 'zh': '风景', ...}

    # 使用統計の取得
    stats = db.get_tag_stats("landscape")
    print(stats)
    # => {'total_uses': 123, 'last_used': '2024-01-22', ...}

高度な操作
========

.. code-block:: python

    # 複数タグの一括処理
    tags_to_add = [
        {"tag": "tag1", "translation": "タグ1"},
        {"tag": "tag2", "translation": "タグ2"}
    ]
    db.bulk_add_tags(tags_to_add)

    # タグの関連性分析
    related = db.find_related_tags("landscape")
    print(related)
    # => ['nature', 'outdoor', 'scenery', ...]

    # カスタムSQLクエリの実行
    results = db.execute_query("""
        SELECT t.tag, tt.translation 
        FROM tags t 
        JOIN tag_translations tt ON t.tag_id = tt.tag_id 
        WHERE tt.language = 'ja'
        LIMIT 5
    """)
    for row in results:
        print(row)

エラーハンドリング
==============

.. code-block:: python

    try:
        db.add_tag("existing_tag")
    except DuplicateTagError:
        print("タグが既に存在します")
    except DatabaseError as e:
        print(f"データベースエラー: {e}")
    finally:
        db.close()
