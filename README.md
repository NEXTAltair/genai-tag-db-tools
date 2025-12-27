# genai-tag-db-tools

## 概要

**genai-tag-db-tools** は、画像生成AIで使用するタグを統合的に管理するためのデータベースツールである。
異なるプラットフォームやフォーマットで用いられるタグ情報を一元的に扱うことが可能となる。

主な目的は以下の通りだ。

- タグとその翻訳、使用頻度、関連性を統合管理
- タグタイプやフォーマットとの関連付けによるフィルタリングや統計分析
- GUIによるタグデータ参照・更新
- CLI経由の起動およびモジュールとして他プロジェクトからの利用が可能

## 主な機能

- タグの管理：新規登録、更新、エイリアス設定、推奨タグ設定など
- タグの参照：キーワード検索、翻訳参照、使用回数やタイプ・フォーマット別の統計表示
- GUIの提供：CLIコマンドからGUIを起動し、直感的にタグデータベースを閲覧・更新
- モジュール機能の提供：他プロジェクトからインポートし、データベース操作やタグ管理ロジックを活用可能

## インストール方法

### 環境要件

- Python 3.12以上
- [uv](https://docs.astral.sh/uv/) (Python package and project manager)
- Windows 11 / Linux対応

### インストール手順

1. uvのインストール（未インストールの場合）

   macOS/Linux:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   Windows:
   ```powershell
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. リポジトリをクローン

   ```bash
   git clone https://github.com/NEXTAltair/genai-tag-db-tools.git
   cd genai-tag-db-tools
   ```

3. 依存関係を同期（自動的に仮想環境を作成し依存パッケージをインストール）

   ```bash
   uv sync
   ```

## 使用方法

### GUIの起動

プロジェクト環境で実行（uv run がプロジェクトの仮想環境を自動的に使用）

```bash
uv run tag-db
```

Pythonモジュールとして直接実行

```bash
uv run python -m genai_tag_db_tools
```

### 他プロジェクトでの利用

`genai_tag_db_tools` をインポートし、データベース操作やタグ管理機能を他プロジェクト内から利用できる。

```python
from genai_tag_db_tools import initialize_tag_cleaner, initialize_tag_searcher

# タグクリーニング
cleaner = initialize_tag_cleaner()
cleaned = cleaner.clean_tags("1girl,  standing___pose")

# タグ検索
searcher = initialize_tag_searcher()
results = searcher.search_tags("girl")
```

詳細なAPI仕様は[API Documentation](#api-documentation)を参照。

## プロジェクト構造

```bash
genai-tag-db-tools/
├── src/
│   └── genai_tag_db_tools/  # メインパッケージ
│       ├── db/              # データベース操作
│       │   ├── repository.py  # リポジトリパターン
│       │   ├── schema.py      # SQLAlchemyスキーマ
│       │   └── runtime.py     # ランタイム設定
│       ├── gui/             # GUI関連
│       │   ├── designer/    # UI定義ファイル(.ui/.py)
│       │   ├── widgets/     # 各種ウィジェット
│       │   └── windows/     # メインウィンドウ
│       ├── io/              # I/O操作
│       │   └── hf_downloader.py  # Hugging Faceダウンローダ
│       ├── services/        # アプリケーションサービス
│       │   ├── tag_search.py    # タグ検索サービス
│       │   └── app_services.py  # アプリケーションサービス
│       ├── utils/           # ユーティリティ
│       │   └── cleanup_str.py   # タグクリーニング
│       ├── core_api.py      # コアAPI
│       ├── models.py        # Pydanticモデル
│       └── main.py          # エントリーポイント
├── tests/                   # テストコード
│   ├── gui/                 # GUIテスト
│   └── unit/                # ユニットテスト
├── pyproject.toml           # プロジェクト設定
└── README.md
```

## データベース概要

主にSQLiteを用いてタグデータを管理する。
**重要**: タグデータベースはHugging Faceから自動的にダウンロードされ、標準キャッシュディレクトリ（`~/.cache/huggingface/hub/`）に保存される。初回起動時に自動ダウンロードが実行される。

以下はエンティティとリレーションを示したER図。

### ER図

```mermaid
erDiagram
    TAGS ||--o{ TAG_TRANSLATIONS : has
    TAGS ||--o{ TAG_STATUS : has
    TAGS ||--o{ TAG_USAGE_COUNTS : tracks
    TAG_FORMATS ||--o{ TAG_STATUS : defines
    TAG_FORMATS ||--o{ TAG_USAGE_COUNTS : tracks
    TAG_TYPE_FORMAT_MAPPING ||--o{ TAG_STATUS : maps
    TAG_TYPE_NAME ||--o{ TAG_TYPE_FORMAT_MAPPING : references

    TAGS {
        int tag_id PK
        string source_tag
        string tag
        datetime created_at
        datetime updated_at
    }

    TAG_TRANSLATIONS {
        int translation_id PK
        int tag_id FK
        string language
        string translation
        datetime created_at
        datetime updated_at
    }

    TAG_FORMATS {
        int format_id PK
        string format_name UK
        string description
    }

    TAG_TYPE_NAME {
        int type_name_id PK
        string type_name UK
        string description
    }

    TAG_TYPE_FORMAT_MAPPING {
        int format_id PK_FK
        int type_id PK
        int type_name_id FK
        string description
    }

    TAG_USAGE_COUNTS {
        int tag_id PK_FK
        int format_id PK_FK
        int count
        datetime created_at
        datetime updated_at
    }

    TAG_STATUS {
        int tag_id PK_FK
        int format_id PK_FK
        int type_id FK
        boolean alias
        int preferred_tag_id FK
        boolean deprecated
        datetime deprecated_at
        datetime source_created_at
        datetime created_at
        datetime updated_at
    }

    DATABASE_METADATA {
        string key PK
        string value
    }
```

### テーブル関係

- **TAGS**: タグの基本情報（tag_id, source_tag, tag）
- **TAG_TRANSLATIONS**: タグ翻訳情報（日本語・英語など多言語対応）
- **TAG_FORMATS**: タグのフォーマット定義（danbooru, e621, rule34など）
- **TAG_TYPE_NAME**: タグタイプ定義（character, copyright, artist, general, meta）
- **TAG_TYPE_FORMAT_MAPPING**: 各フォーマットとタイプの対応関係
- **TAG_USAGE_COUNTS**: タグのフォーマット別使用回数統計
- **TAG_STATUS**: タグの状態管理（エイリアス、推奨タグ、非推奨フラグ、作成日時）
- **DATABASE_METADATA**: データベースメタ情報（バージョン、ダウンロード日時など）

## データソース

以下のデータソースを参考・利用。

1. [DominikDoom/a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete): tags.dbの基となったCSVタグデータ
2. [applemango氏による日本語翻訳](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete/discussions/265): CSVタグデータの日本語翻訳
3. としあき製作のCSVタグデータの日本語翻訳
4. [AngelBottomless/danbooru-2023-sqlite-fixed-7110548](https://huggingface.co/datasets/KBlueLeaf/danbooru2023-sqlite): danbooruタグのデータベース
5. [hearmeneigh/e621-rising-v3-preliminary-data](https://huggingface.co/datasets/hearmeneigh/e621-rising-v3-preliminary-data): e621およびrule34タグのデータベース
6. [p1atdev/danbooru-ja-tag-pair-20241015](https://huggingface.co/datasets/p1atdev/danbooru-ja-tag-pair-20241015): danbooruタグの日本語翻訳データベース
7. [toynya/Z3D-E621-Convnext](https://huggingface.co/toynya/Z3D-E621-Convnext): e621 tagger convnext model のタグcsv #TODO: まだ反映させてない
8. [Updated danbooru.csv(2024-10-16) for WebUI Tag Autocomplete](https://civitai.com/models/862893?modelVersionId=965482): WebUI Tag Autocompleteのデフォルトのdanbooru.csvはやや古くなっているようなので、2024年10月16日時点での新しいデータに更新しました。#TODO: まだ反映させてない

## API Documentation

### 公開API

パッケージから直接インポート可能な主要機能：

```python
from genai_tag_db_tools import (
    # ファクトリ関数
    initialize_tag_cleaner,
    initialize_tag_searcher,

    # コアAPI関数
    build_downloaded_at_utc,
    convert_tags,
    ensure_databases,
    get_statistics,
    get_tag_formats,
    register_tag,
    search_tags,

    # クラス
    TagCleaner,
    TagSearcher,
)
```

### TagCleaner

タグ文字列のクリーニング・正規化を行うクラス。

**主なメソッド**:
- `clean_format(tags: str) -> str`: タグフォーマットのクリーニング
- `clean_tags(tag: str) -> str`: 個別タグのクリーニング（重複除去、アンダースコア正規化）
- `clean_caption(caption: str) -> str`: キャプション文のクリーニング
- `convert_prompt(prompt: str) -> str`: プロンプト文の変換

**使用例**:
```python
cleaner = initialize_tag_cleaner()
cleaned = cleaner.clean_tags("1girl,  standing___pose")
# -> "1girl, standing_pose"
```

### TagSearcher

タグデータベースの検索・変換を行うクラス。

**主なメソッド**:
- `search_tags(query: str, ...) -> list[TagSearchRow]`: タグ検索
- `convert_tag(tag: str, format_name: str) -> str | None`: タグ変換
- `get_tag_formats() -> list[str]`: タグフォーマット一覧取得
- `get_format_id(format_name: str) -> int | None`: フォーマットID取得

**使用例**:
```python
searcher = initialize_tag_searcher()
results = searcher.search_tags("girl")
converted = searcher.convert_tag("1girl", "danbooru")
```

### コアAPI関数

#### `convert_tags(repo, tags: str, format_name: str, separator: str = ", ") -> str`

カンマ区切りタグを指定フォーマットに一括変換。

**パラメータ**:
- `repo`: MergedTagReaderインスタンス
- `tags`: カンマ区切りタグ文字列
- `format_name`: 変換先フォーマット名（"danbooru", "e621"など）
- `separator`: 出力時の区切り文字（デフォルト: ", "）

**戻り値**: 変換後のタグ文字列

#### `search_tags(repo, request: TagSearchRequest) -> TagSearchResult`

タグデータベースの高度な検索機能。

**主要フィルタ**:
- `query`: 検索クエリ文字列
- `format_names`: フォーマット指定
- `type_names`: タグタイプ指定（character, copyright, artistなど）
- `min_usage` / `max_usage`: 使用回数範囲
- `include_aliases`: エイリアスを含むか
- `resolve_preferred`: 推奨タグに解決するか

#### `get_statistics(repo) -> TagStatisticsResult`

データベース全体の統計を取得。

**戻り値フィールド**:
- `total_tags`: 総タグ数
- `total_aliases`: エイリアス数
- `total_formats`: フォーマット数
- `total_types`: タグタイプ数

### データベースアクセス

```python
from genai_tag_db_tools.db.repository import get_default_reader

# 読み取り専用リポジトリ取得
repo = get_default_reader()
```

## ライセンス

本プロジェクトはMITライセンス下で公開している。詳細は[LICENSE](LICENSE)を参照。
