.. _dev_guide:

Developer Guide (開発者向けセットアップガイド)
==============================================================
開発環境の構築やコードスタイル、テスト実行など、開発に必要な手順の説明。

## システム構成

1. **データ層 (Data Layer)**

    - SQLiteデータベースを用いてタグ情報を管理｡
    - データベースには基本的なタグ情報(TAGSテーブル)、翻訳情報(TAG\_TRANSLATIONSテーブル)、使用頻度(TAG\_USAGE\_COUNTSテーブル)などを保持｡
    - 初期データは開発時に外部CSVから一括インポートし、その後DBファイルをGitHubリポジトリにコミット。
    - 現在はGUI操作によるタグの閲覧や参照が中心で、手動での追加・編集は限定的です(将来的に必要時に機能拡張予定)。
    - 後ほど別のプログラムから当DBに存在しないタグが検索された場合は、ユーザーによるタグ登録を行いたい構想があるが現状は後回し。
    - データベースへの更新操作は行われるたびに即時反映(オートコミット)する設計(設計変更の可能性あり)。
    - シングルユーザー環境を想定。

2. **ビジネスロジック層 (Business Logic Layer)**

    - タグの登録・更新・翻訳取得・使用頻度計測などの機能を実装
    - データベースアクセスを抽象化し、タグ形式の差異を吸収するロジックを提供

    2.1 service
        - app_service.py: guiで使用するサービス層のロジックを提供
        - import_data.py: csvやHuggingFaceのタグデータをDBにインポートするロジックを提供
        - polars_schema.py: Polarsのスキーマを定義し、データフレームをDBにインポートするロジックを提供 TODO: コレ必要か?
        - tag_register.py: タグ登録機能を提供するロジック
        - tag_search.py: タグ検索機能を提供するロジック
        - tag_statistics.py: タグ使用頻度など統計機能を提供するロジック

3. **インターフェース層 (Interface Layer)**

    - PySide6を用いたGUIを提供し、タグ情報を直感的に参照・更新
    - `pyproject.toml` の `scripts` セクションを利用してGUIを起動可能
    - CLIによる直接操作は未対応で、GUI起動以外のCLI操作は現時点では未実装。

## 開発環境のセットアップ

1. リポジトリをクローン:

.. code-block:: bash

    git clone https://github.com/NEXTAltair/genai-tag-db-tools.git
    cd genai-tag-db-tools

2. 仮想環境を作成し、パッケージをdevモードでインストール:

.. code-block:: bash

    python3.12 -m venv venv
    venv\Scripts\activate
    cd genai_tag_db_tools
    pip install -e .[dev]

**注意**: Windows以外のOS(macOS/Linux)は未対応。

## コードスタイルチェック

`black` と `ruff` を用いてコードのフォーマットおよびLintチェックを行います。
これらのツールはPEP 8基準を自動的に適用。

.. code-block:: bash

    black genai_tag_db_tools
    ruff genai_tag_db_tools

## テスト実行

`pytest` を用いてユニットテストを実行。

.. code-block:: bash

    pytest tests

テスト実行時にカバレッジレポートを生成する場合は、以下のコマンドを使用。

.. code-block:: bash

    pytest --cov=genai_tag_db_tools --cov-report=term-missing

## 開発時のドキュメンテーション更新

ドキュメントを更新したら、以下の手順でHTML形式で再生成して確認する。

1. **RSTファイルの生成** (必要に応じて):
    新しいモジュールやパッケージを追加した場合や大きな変更があった場合は、以下のコマンドを実行してRSTファイルを生成する。

.. code-block:: bash

    sphinx-apidoc -o source ../genai_tag_db_tools

- `source` はRSTファイルの出力先ディレクトリ
- `../genai_tag_db_tools` はドキュメント化するPythonパッケージのパス

2. **ドキュメント生成**:
    以下のコマンドを実行してHTML形式のドキュメントを生成する。

.. code-block:: bash

    sphinx-build -b html . _build/html

3. **確認**:
    生成された `_build/html` ディレクトリ内の `index.html` をブラウザで開いて内容を確認する。

## 主な機能

- **タグ管理機能**:

    - タグ情報の閲覧(GUIによる検索・参照)
    - 後々タグ登録や削除などを行えるようにする計画あり(現時点ではデータは初期インポート済み)

- **翻訳・対応関係管理**:

    - TAG\_TRANSLATIONSテーブルにより、一つのタグに対して複数言語の翻訳を管理
    - Danbooruタグ・e621タグ・日本語タグなど、複数フォーマットや言語間を参照可能
    - 画像生成AIで使用するカンマ区切りプロンプトを基に、内部DBのタグへマッピング

- **統計・使用頻度情報**:

    - TAG\_USAGE\_COUNTSテーブルでタグ毎の使用回数を記録
    - よく使われるタグを参照することで、GUI上で人気タグの確認が可能

## エラーハンドリングとロギング

- SQLite操作時、``try-except`` でエラーを捕捉し、重大なエラーは ``logs/error.log`` に記録｡
- GUI上でエラーが発生した場合には、ポップアップでユーザーにエラーメッセージを通知｡
- ログファイルは本ツールの実行ディレクトリ下( ``logs/`` フォルダなど)に保存。

## 性能試験結果

- **SQLiteでの検索・更新性能(想定例)**:
    - 1万件程度のタグに対して、全文検索(LIKE検索)を行った場合、GUI表示まで約0.2秒程度
    - インデックス付与後は検索速度が2倍以上高速化
- **GUIの応答時間**:
    - タグ一覧表示や翻訳切り替えはほぼ即時
    - 大量データ(数十万タグ)対応時には遅延発生の可能性があるが、現段階でそのレベルのスケールは想定外
- 性能改善策として、必要に応じてインデックスの最適化やメモリキャッシュ導入を検討可能。

## 他プロジェクトとの連携事例(モジュールとしての利用例)

他プロジェクトでは、本ツールの機能をPythonモジュールとしてインポートすることでタグデータ検索や翻訳機能を利用可能
以下はサンプルコード例｡

.. code-block:: python

    from genai_tag_db_tools.core import TagManager

    # TagManagerはデータベースへの接続とタグ操作機能を提供するクラス
    manager = TagManager(db_path="genai_tags.db")

    # タグ検索例 : 特定のタグ名でTAGSテーブルを検索
    results = manager.find_tags_by_name("cat")
    for tag in results:
        print(tag.tag_id, tag.tag, tag.source_tag)

    # 翻訳取得例：特定のタグの日本語翻訳を取得
    jp_translation = manager.get_translation(tag_id=123, language="ja")
    if jp_translation:
        print("Japanese Translation:", jp_translation.translation)

※APIインターフェースは内部実装を直接呼び出す形で、現在は正式な外部向けAPIとして定義してない。将来的に明確なAPIレイヤーを整備するかも。

## 今後の整備の流れ

本ツールをより読みやすく保守しやすい形にするため、以下のステップを想定しています。

1. **ディレクトリ構成の見直し**
   - `data/` と `db/` ディレクトリに重複する機能や責務がないか確認
   - 不要なファイルや重複コードの整理

2. **コードの再構成**
   - ロジックとデータアクセスの役割分担を明確にし、GUI層からビジネスロジック・DB操作のコードを切り出す
   - 重複する正規表現の処理等は `TagCleaner` などに集約し、ユーティリティ化

3. **GUIとサービス層の分離**
   - GUIのクリックイベントやウィジェット上での処理を最小限に留め、ビジネスロジックはサービス層に委譲
   - Qt Designer で生成されたUIファイルはレイアウトとイベント結合に専念

4. **大きなメソッドや例外ハンドリングの細分化**
   - 長大な処理や多数のtry-exceptを小さなメソッドに分け、保守性向上
   - テストしやすいようにそれぞれの処理を単独メソッド化

5. **リファクタリング & テスト・ドキュメント更新**
   - 構成変更後、`pytest` によるテストを継続的に実施
   - ドキュメント(`.rst`ファイル)や docstring を追加・更新してメンテナンス性向上

6. **継続的な改善と運用**
   - 大規模データや他プロジェクト連携などの要件が増加した場合、さらなるインデックス最適化やAPIレイヤー追加も検討
   - プロジェクト運用の中で逐次リファクタリング＆ドキュメント拡充を行うことを推奨
