===================================
データベース設計
===================================

このページでは、`genai-tag-db-tools` のデータベース構造と設計。

- データベースの全体構造
- テーブル定義とその説明
- Alembic を用いたスキーマ変更の管理方法

## データベースの概要

本プロジェクトでは、SQLite をデータベースエンジンとして使用し、タグ情報の統合管理を行う。データベースには以下の情報が格納。

- 基本的なタグ情報（`TAGS` テーブル）
- タグの翻訳情報（`TAG_TRANSLATIONS` テーブル）
- 使用頻度や統計情報（`TAG_USAGE_COUNTS` テーブル）
- タグ形式や関連情報（`TAG_FORMATS` テーブルなど）

## テーブル構成と定義

以下に各テーブルの構成とその役割。

### TAGS テーブル

基本的なタグ情報を保持するテーブル。

- **tag\_id** (INTEGER, PK): 全てのタグに対する一意のID（連番int）。
- **source\_tag** (TEXT): アンダースコア区切り､()のエスケープ処理がされていない画像サイトで使用される形態のタグ形式。
  - 例: `artoria_pendragon_(fate)`
- **tag** (TEXT, UNIQUE, NOT NULL): プロンプトで使用する形式に正則化したタグ。
  - 例: `artoria pendragon \(fate\)`
- **created\_at** (DATETIME): 登録日時のタイムスタンプ。
  - 取り込んだデータに含まれる場合は最古の日時、それ以外はデータベース登録日時。
- **updated\_at** (DATETIME): 更新日時のタイムスタンプ。
  - 取り込んだデータに含まれる場合は最新の日時、それ以外はデータベース登録日時。

### TAG\_TRANSLATIONS テーブル

一つのタグに対する多言語翻訳情報を保持するテーブル。 基本的に英語なので､英語は登録されない｡

- **translation\_id** (INTEGER, PK): 翻訳情報の一意のID（連番int）。
- **tag\_id** (INTEGER, FK): 対応するタグのID。
- **language** (TEXT): 翻訳言語（BCP 47形式）。
  - 例: `ja-JP`, `zh-Hans`, `zh-Hant`
- **translation** (TEXT): 言語に対応する翻訳文字列。
  - 例\:monochrome `モノクロ`, `单色画`, `單色畫`, `单色图片`
- **created\_at** (DATETIME): 登録日時。
- **updated\_at** (DATETIME): 更新日時。

### TAG\_FORMATS テーブル

使われているサイトを定義｡ フォーマットという言い方でいいのかは疑問が残る｡

- **format\_id** (INTEGER, PK): タグ形式の一意のID（連番int）。
- **format\_name** (TEXT): タグ形式の名称。
  - 例: `Danbooru`, `e621`
- **description** (TEXT): タグ形式の説明。
  - 必要時に利用可能な補足情報。

### TAG\_TYPE\_NAME テーブル

タグタイプ情報を管理するテーブル。

- **type\_name\_id** (INTEGER, PK): タグタイプの一意のID（連番int）。
- **type\_name** (TEXT): タグタイプ名。
  - 例: `Character`, `Artist`
- **description** (TEXT): タグタイプの説明。

### TAG\_TYPE\_FORMAT\_MAPPING テーブル

タグタイプとフォーマットの対応関係を管理する中間テーブル。

- **format\_id** (INTEGER, PK, FK): 対応するフォーマットのID。
- **type\_id** (INTEGER, PK): タグタイプの一意のID。
- **type\_name\_id** (INTEGER, FK): タグタイプ名のID。
- **description** (TEXT): フォーマットとタイプ間の関係性説明。

### TAG\_USAGE\_COUNTS テーブル

タグの使用回数情報を管理するテーブル。

- **tag\_id** (INTEGER, PK, FK): 対応するタグのID。
- **format\_id** (INTEGER, PK, FK): 対応するフォーマットのID。
- **count** (INTEGER): タグの使用回数。
- **created\_at** (DATETIME): 登録日時。
- **updated\_at** (DATETIME): 更新日時。

### TAG\_STATUS テーブル

タグのエイリアスや推奨タグ情報を管理するテーブル。

- **tag\_id** (INTEGER, PK, FK): 対応するタグのID。
- **alias** (BOOLEAN): 同義語・類義語であるか。
    - True の場合、非推奨タグ。
- **preferred\_tag\_id** (INTEGER, FK): 推奨タグのID。
    - エイリアスでない場合は自身のIDを持つ。
- **created\_at** (DATETIME): 登録日時。
- **updated\_at** (DATETIME): 更新日時。

## フォーマットとタイプの関係

`TAG_FORMATS` と `TAG_TYPE_NAME` は多対多の関係にあり、その関係を `TAG_TYPE_FORMAT_MAPPING` によって管理。

- **多対多関係の理由**:
    - フォーマットやタイプの追加時に変更箇所を最小化。
    - 例: `Danbooru` (format\_id = 1) における `Artist` (type\_id = 1) と `type_name_id = 2` の対応。

- **例:**
    `TAG_TYPE_FORMAT_MAPPING` に以下のようなエントリが追加される場合：
    - `format_id=1` (Danbooru) と `type_id=1` を照合して、`type_name_id=2` (Artist) の情報を得る

## Alembic を用いたスキーマ管理

スキーマ変更には Alembic を使用します。以下は基本的な操作例。

.. code-block:: bash

    # Alembic 初期化
    alembic init alembic

    # 新しいマイグレーションスクリプトの作成
    alembic revision -m "Add new table"

    # スキーマ変更の適用
    alembic upgrade head


### Alembic の具体例

以下は、`TAGS` テーブルに新しいカラム `is_active` を追加する例。

1. マイグレーションスクリプトを作成:

.. code-block:: bash

    alembic revision -m "Add is_active column to TAGS table"

2. 自動生成されたスクリプトに以下のコードを追加:

.. code-block:: python

    def upgrade():
        op.add_column('TAGS', sa.Column('is_active', sa.Boolean(), nullable=True))

    def downgrade():
        op.drop_column('TAGS', 'is_active')

3. スキーマ変更を適用:

.. code-block:: bash

    alembic upgrade head

Alembic を使うことで、スキーマ変更を安全かつ計画的に管理できる｡

詳細な例やスクリプトの使用方法は `dev_guide.rst` を参照。
