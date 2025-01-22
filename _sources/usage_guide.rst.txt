.. _usage_guide:

Usage Guide (機能ガイド)
=========================

このガイドでは、``genai-tag-db-tools`` の基本的な機能利用方法。

GUIの起動
----------
PySide6ベースのGUIを用いてタグの検索・登録を行うことができます。

.. code-block:: bash

    genai-tag-db-tools-gui

起動後、次のような画面が表示されます（スクリーンショット例を配置可能な場合はここに挿入）:

- 検索フィールドにタグ名の一部を入力してエンターを押すと、該当するタグが一覧表示されます。
- 新規タグを登録するには「Add Tag」ボタンをクリックし、タグ名や翻訳情報を入力します。

SQLiteデータベースの操作例
---------------------------
本ツールはSQLiteデータベースを内部的に用いてタグ情報を保存します。

Pythonコードから直接タグを操作する例:

.. code-block:: python

    from genai_tag_db_tools import TagDatabase

    db = TagDatabase("path_to_your_db.sqlite")
    tag_info = db.search_tag("landscape")
    print(tag_info)
    # => [{'tag': 'landscape', 'translation': '風景', 'aliases': [], 'count': 123}, ...]

    db.add_tag("new_tag", translation="新しいタグ", aliases=["nt"], count=1)
