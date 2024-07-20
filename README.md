# タグデータベースツール

## 概要

異なるプラットフォーム間でタグ、その翻訳、使用回数、関連性を統一したデータベースとして作成することを目的としています。

## データベース構造

データベースはSQLiteで実装されており、以下の主要なテーブルで構成されています：

1. `TAGS`: ソースと正規化された形式を含む、ユニークなタグを保存します。
2. `TAG_TRANSLATIONS`: 異なる言語でのタグの翻訳を含みます。
3. `TAG_FORMATS`: タグの異なるフォーマットまたはソース（例：danbooru、e621、derpibooru）を定義します。
4. `TAG_TYPES`: タグを種類（例：一般、アーティスト、著作権、キャラクター）に分類します。
5. `TAG_TYPE_FORMAT_MAPPING`: タグの種類を特定のフォーマットにマッピングします。
6. `TAG_USAGE_COUNTS`: 異なるフォーマットでのタグの使用回数を追跡します。
7. `TAG_STATUS`: タグのステータス（エイリアスや推奨形式を含む）を管理します。

追加テーブルには様々なソースからの生データが含まれます。

## 特徴

- タグ翻訳の多言語サポート
- 異なるプラットフォーム間でのタグ種類の分類
- エイリアスと推奨タグの管理
- 異なるフォーマットでのタグ使用回数の追跡
- 非推奨タグや正規化を含む包括的なタグ情報

## データソース

このプロジェクトは以下の主要なデータソースを使用しています：

1. [DominikDoom/a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete): tags.dbの基となったCSVタグデータ
2. [applemango氏による日本語翻訳](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete/discussions/265): CSVタグデータの日本語翻訳
3. としあき製作のCSVタグデータの日本語翻訳
4. [AngelBottomless/danbooru-2023-sqlite-fixed-7110548](https://huggingface.co/datasets/KBlueLeaf/danbooru2023-sqlite): danbooruタグのデータベース
5. [hearmeneigh/e621-rising-v3-preliminary-data](https://huggingface.co/datasets/hearmeneigh/e621-rising-v3-preliminary-data): e621およびrule34タグのデータベース

これらのデータソースを統合し、整理することで、包括的かつ多言語対応のタグデータベースを構築しています。


## ライセンス

MIT


# V3
```mermaid
erDiagram
    TAGS ||--o{ TAG_TRANSLATIONS : has
    TAGS ||--o{ TAG_USAGE_COUNTS : has
    TAGS ||--o{ TAG_STATUS : has
    TAGS ||--o{ TAG_STATUS : is_preferred_by
    TAG_FORMATS ||--o{ TAG_USAGE_COUNTS : has
    TAG_FORMATS ||--o{ TAG_TYPE_FORMAT_MAPPING : has
    TAG_TYPE_NAME ||--o{ TAG_TYPE_FORMAT_MAPPING : defines
    TAG_TYPE_FORMAT_MAPPING ||--o{ TAG_STATUS : defines
    
    TAGS {
        int tag_id PK
        string source_tag
        string tag
    }
    
    TAG_TRANSLATIONS {
        int translation_id PK
        int tag_id FK
        string language
        string translation
    }
    
    TAG_FORMATS {
        int format_id PK
        string format_name
        string description
    }
    
    TAG_TYPE_NAME {
        int type_name_id PK
        string type_name
        str   string description
    }
    
    TAG_USAGE_COUNTS {
        int format_id PK, FK
        int count
    }
    
    TAG_STATUS {
        int tag_id PK, FK
        int tag_id PK, FK
        int format_id PK, FK
        int type_id FK
        boolean alias
        int preferred_tag_id FK
    } ing description
    }
    
    TAG_TYPE_FORMAT_MAPPING {
        int format_id PK, FK
        int type_id PK
        int type_name_id FK
     
```