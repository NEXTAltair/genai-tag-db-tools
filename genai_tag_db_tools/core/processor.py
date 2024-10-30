import sqlite3
import csv
import re
from pathlib import Path
from collections import defaultdict


class CSVToDatabaseProcessor:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.current_id: int = 0
        self.tags: dict[int, tuple[str, str]] = (
            {}
        )  # {tag_id: (source_tag, normalized_tag)}
        self.tag_id_map: dict[tuple[str, str], int] = (
            {}
        )  # {(source_tag, normalized_tag): tag_id}
        self.translations: dict[int, set[tuple[str, str]]] = defaultdict(
            set
        )  # {tag_id: {(language, translation)}}
        self.usage_counts: dict[tuple[int, int], int] = defaultdict(
            int
        )  # {(tag_id, format_id): count}
        self.tag_status: dict[tuple[int, int], tuple[int, bool, int]] = (
            {}
        )  # {(tag_id, format_id): (type_id, alias, preferred_tag_id)}

    def process_csv_files(self, csv_dir: Path):
        for file_path in csv_dir.rglob("*.csv"):
            print(f"Processing {file_path.name}...")
            self.process_single_csv(file_path)
            # 各ファイル処理後にデータベースに挿入
            self.insert_into_final_tables()
            # メモリを節約するためにクラス変数をクリア
            # self.clear_temporary_data()

    def clear_temporary_data(self):
        self.translations.clear()
        self.usage_counts.clear()
        self.tag_status.clear()

    def process_single_csv(self, file_path: Path):
        format_id = self.get_format_id(file_path.stem)
        default_type_id = self.get_default_type_id(file_path.stem)
        with file_path.open("r", newline="", encoding="utf-8") as csvfile:
            csv_reader = csv.DictReader(csvfile)
            for row in csv_reader:
                self.process_row(row, format_id, default_type_id)

    def process_row(self, row: dict, format_id: int, default_type_id: int):
        source_tag = row["source_tag"]
        normalized_tag = CSVToDatabaseProcessor.normalize_tag(source_tag)

        # タグの処理とIDの取得
        tag_id = self.get_tag_id(source_tag, normalized_tag)

        # 使用回数の処理
        count = self.safe_int_convert(row.get("count", "0"))
        self.usage_counts[(tag_id, format_id)] += count

        # 翻訳の処理
        self.process_translations(tag_id, row)

        # deprecated_tags の処理
        self.process_deprecated_tags(tag_id, format_id, row)

        # タグステータスの処理
        type_id = self.safe_int_convert(row.get("type_id", ""), default_type_id)
        current_status = self.tag_status.get(
            (tag_id, format_id), (type_id, False, tag_id)
        )
        self.tag_status[(tag_id, format_id)] = (
            type_id,
            current_status[1],
            current_status[2],
        )

    def get_tag_id(self, source_tag: str, normalized_tag: str) -> int:
        key = (source_tag, normalized_tag)
        if key not in self.tag_id_map:
            self.current_id += 1
            self.tag_id_map[key] = self.current_id
            self.tags[self.current_id] = key
        return self.tag_id_map[key]

    def process_translations(self, tag_id: int, row: dict):
        for lang in ["japanese", "zh-Hant"]:
            if lang in row and row[lang]:
                translations = self.split_compound_field(row[lang])
                for trans in translations:
                    self.translations[tag_id].add((lang, trans))

    def process_deprecated_tags(self, tag_id: int, format_id: int, row: dict):
        deprecated_tags_str = row.get("deprecated_tags", "")
        if deprecated_tags_str:
            deprecated_tags = self.split_compound_field(deprecated_tags_str)
            for deprecated_tag in deprecated_tags:
                normalized_deprecated_tag = CSVToDatabaseProcessor.normalize_tag(
                    deprecated_tag
                )
                deprecated_tag_id = self.get_tag_id(
                    deprecated_tag, normalized_deprecated_tag
                )

                # 元のタグのステータスを更新
                original_type_id = self.tag_status.get(
                    (tag_id, format_id), (0, False, tag_id)
                )[0]
                self.tag_status[(tag_id, format_id)] = (original_type_id, False, tag_id)

                # エイリアスに対してエントリを作成または更新
                self.tag_status[(deprecated_tag_id, format_id)] = (
                    original_type_id,
                    True,
                    tag_id,
                )

    def split_compound_field(self, field: str) -> set[str]:
        if not field:
            return set()
        return {item.strip() for item in field.split(",")}

    @staticmethod
    def safe_int_convert(value: str, default: int = 0) -> int:
        try:
            return int(value)
        except ValueError:
            return default

    @staticmethod
    def normalize_tag(tag: str) -> str:
        tag = tag.lower()
        tag = re.sub(r"_\(", r" (", tag)
        tag = tag.replace("(", r"\(").replace(")", r"\)")
        tag = re.sub(r"_", " ", tag)
        tag = re.sub(r"\s+", r" ", tag)
        tag = tag.strip()
        return tag

    def get_format_id(self, filename: str) -> int:
        # DominikDoom/a1111-sd-webui-tagcomplete: CSVファイル名からフォーマットIDを取得
        id0 = ["EnglishDictionary", "Tags_zh_full"]
        id1 = ["danbooru_klein10k_jp", "danbooru_machine_jp", "danbooru"]
        id2 = [
            "dataset_rising_v2",
            "e621_sfw",
            "e621_tags_jsonl",
            "e621",
            "rising_v2",
            "rising_v3",
        ]
        id3 = ["derpibooru"]

        if filename in id0:
            return 0
        elif filename in id1:
            return 1
        elif filename in id2:
            return 2
        elif filename in id3:
            return 3
        else:
            print(f"Warning: {filename} フォーマットID不明とりあえず0")
            return 0

    def get_default_type_id(self, filename: str) -> int:
        # CSVファイル名からデフォルトのtype_idを取得
        danbooru_types = {
            "danbooru_general": 0,
            "danbooru_artist": 1,
            "danbooru_copyright": 3,
            "danbooru_character": 4,
            "danbooru_meta": 5,
        }
        e621_types = {
            "e621_general": 0,
            "e621_artist": 1,
            "e621_copyright": 3,
            "e621_character": 4,
            "e621_species": 5,
            "e621_invalid": 6,
            "e621_meta": 7,
            "e621_lore": 8,
        }
        derpibooru_types = {
            "derpibooru_general": 0,
            "derpibooru_species": 3,
            "derpibooru_character": 4,
            "derpibooru_rating": 5,
            "derpibooru_origin": 8,
        }

        for type_name, type_id in {
            **danbooru_types,
            **e621_types,
            **derpibooru_types,
        }.items():
            if type_name in filename:
                return type_id

        # デフォルトはgeneral (0)を返す
        return 0

    def create_final_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # TAGSテーブルの作成
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS TAGS (
            tag_id INTEGER PRIMARY KEY,
            source_tag TEXT,
            tag TEXT NOT NULL,
            UNIQUE(tag, source_tag)
        )
        """
        )

        # TAG_TRANSLATIONSテーブルの作成
        # NOTE: UNIQUE制約 類語の重複は許すが同じ文字列は許さない
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS TAG_TRANSLATIONS (
            translation_id INTEGER PRIMARY KEY,
            tag_id INTEGER,
            language TEXT NOT NULL,
            translation TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (tag_id) REFERENCES TAGS(tag_id),
            UNIQUE(tag_id, language, translation)
        )
        """
        )

        # TAG_FORMATSテーブルの作成と初期データの挿入
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS TAG_FORMATS (
            format_id INTEGER PRIMARY KEY,
            format_name TEXT NOT NULL,
            description TEXT
            UNIQUE(format_name)
        )
        """
        )
        cursor.executemany(
            """
        INSERT OR IGNORE INTO TAG_FORMATS (format_id, format_name, description)
        VALUES (?, ?, ?)
        """,
            [
                (0, "unknown", ""),
                (1, "danbooru", ""),
                (2, "e621", ""),
                (3, "derpibooru", ""),
            ],
        )

        # TAG_TYPE_NAMEテーブルの作成と初期データの挿入
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS TAG_TYPE_NAME (
            type_name_id INTEGER PRIMARY KEY,
            type_name TEXT NOT NULL,
            description TEXT
        )
        """
        )
        cursor.executemany(
            """
        INSERT OR IGNORE INTO TAG_TYPE_NAME (type_name_id, type_name, description)
        VALUES (?, ?, ?)
        """,
            [
                (0, "unknown", ""),
                (1, "general", ""),
                (2, "artist", ""),
                (3, "copyright", ""),
                (4, "character", ""),
                (5, "species", ""),
                (6, "invalid", ""),
                (7, "meta", ""),
                (8, "lore", ""),
                (9, "oc", ""),
                (10, "rating", ""),
                (11, "body-type", ""),
                (12, "origin", ""),
                (13, "error", ""),
                (14, "spoiler", ""),
                (15, "content-official", ""),
                (16, "content-fanmade", ""),
            ],
        )

        # TAG_TYPE_FORMAT_MAPPINGテーブルの作成と初期データの挿入
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS TAG_TYPE_FORMAT_MAPPING (
            format_id INTEGER,
            type_id INTEGER,
            type_name_id INTEGER,
            description TEXT,
            PRIMARY KEY (format_id, type_id),
            FOREIGN KEY (format_id) REFERENCES TAG_FORMATS(format_id),
            FOREIGN KEY (type_name_id) REFERENCES TAG_TYPE_NAME(type_name_id)
        )
        """
        )
        cursor.executemany(
            """
        INSERT OR IGNORE INTO TAG_TYPE_FORMAT_MAPPING (format_id, type_id, type_name_id, description)
        VALUES (?, ?, ?, ?)
        """,
            [
                (0, 0, 0, "unknown"),
                (1, 0, 1, "Danbooru general"),
                (1, 1, 2, "Danbooru artist"),
                (1, 3, 3, "Danbooru copyright"),
                (1, 4, 4, "Danbooru character"),
                (1, 5, 7, "Danbooru meta"),
                (2, 6, 6, "e621 invalid"),
                (2, 7, 7, "e621 meta"),
                (2, 8, 8, "e621 lore"),
                (2, 1, 2, "e621 artist"),
                (2, 0, 1, "e621 general"),
                (2, 5, 5, "e621 species"),
                (2, 3, 3, "e621 copyright"),
                (2, 4, 4, "e621 character"),
                (3, 5, 10, "Derpibooru rating"),
                (3, 6, 11, "Derpibooru body-type"),
                (3, 7, 7, "Derpibooru meta"),
                (3, 8, 12, "Derpibooru origin"),
                (3, 9, 13, "Derpibooru error"),
                (3, 10, 14, "Derpibooru spoiler"),
                (3, 11, 16, "Derpibooru content-fanmade"),
                (3, 0, 1, "Derpibooru general"),
                (3, 1, 15, "Derpibooru content-official"),
                (3, 2, 1, "Derpibooru general"),
                (3, 3, 5, "Derpibooru species"),
                (3, 4, 9, "Derpibooru oc"),
            ],
        )

        # TAG_USAGE_COUNTSテーブルの作成
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS TAG_USAGE_COUNTS (
            tag_id INTEGER,
            format_id INTEGER,
            count INTEGER,
            PRIMARY KEY (tag_id, format_id),
            FOREIGN KEY (tag_id) REFERENCES TAGS(tag_id),
            FOREIGN KEY (format_id) REFERENCES TAG_FORMATS(format_id)
        )
        """
        )

        # TAG_STATUSテーブルの作成
        cursor.execute(
            """
        CREATE TABLE IF NOT EXISTS TAG_STATUS (
            tag_id INTEGER,
            format_id INTEGER,
            type_id INTEGER,
            alias BOOLEAN,
            preferred_tag_id INTEGER,
            PRIMARY KEY (tag_id, format_id),
            FOREIGN KEY (tag_id) REFERENCES TAGS(tag_id),
            FOREIGN KEY (format_id) REFERENCES TAG_FORMATS(format_id),
            FOREIGN KEY (format_id, type_id) REFERENCES TAG_TYPE_FORMAT_MAPPING(format_id, type_id),
            FOREIGN KEY (preferred_tag_id) REFERENCES TAGS(tag_id)
        )
        """
        )

        conn.commit()
        conn.close()

    def insert_into_final_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("BEGIN TRANSACTION")

            # TAGSテーブルにデータを挿入
            cursor.executemany(
                """
            INSERT OR IGNORE INTO TAGS (tag_id, source_tag, tag)
            VALUES (?, ?, ?)
            """,
                [
                    (tag_id, source_tag, normalized_tag)
                    for tag_id, (source_tag, normalized_tag) in self.tags.items()
                ],
            )

            # TAG_TRANSLATIONSテーブルにデータを挿入
            translation_data = [
                (tag_id, lang, trans)
                for tag_id, trans_set in self.translations.items()
                for lang, trans in trans_set
            ]
            cursor.executemany(
                """
            INSERT OR REPLACE INTO TAG_TRANSLATIONS (tag_id, language, translation)
            VALUES (?, ?, ?)
            """,
                translation_data,
            )

            # TAG_USAGE_COUNTSテーブルにデータを挿入
            usage_counts_data = [
                (tag_id, format_id, count)
                for (tag_id, format_id), count in self.usage_counts.items()
            ]
            cursor.executemany(
                """
            INSERT OR REPLACE INTO TAG_USAGE_COUNTS (tag_id, format_id, count)
            VALUES (?, ?, ?)
            """,
                usage_counts_data,
            )

            # TAG_STATUSテーブルにデータを挿入
            status_data = [
                (tag_id, format_id, type_id, alias, preferred_tag_id)
                for (tag_id, format_id), (
                    type_id,
                    alias,
                    preferred_tag_id,
                ) in self.tag_status.items()
            ]
            cursor.executemany(
                """
            INSERT OR REPLACE INTO TAG_STATUS (tag_id, format_id, type_id, alias, preferred_tag_id)
            VALUES (?, ?, ?, ?, ?)
            """,
                status_data,
            )

            conn.commit()
            print("Data insertion completed successfully.")
        except sqlite3.Error as e:
            conn.rollback()
            print(f"An error occurred: {e}")
        finally:
            conn.close()

    def deduplicate_data(self):
        """
        クラス変数の重複を削除し、データを整理するメソッド
        """
        # tagsの重複削除
        # tagsは{normalized_tag: (source_tag, normalized_tag)}の形式
        # normalized_tagをキーとして使用しているため、重複は自動的に排除されている
        # 追加の処理は不要

        # translationsの重複削除
        # translationsは{tag: set((language, translation))}の形式
        for tag, translations in self.translations.items():
            # setを使用しているため、重複は自動的に排除されている
            # ただし、同じ翻訳が異なる言語コードで登録されている可能性があるため、言語コードを正規化
            normalized_translations = set()
            for lang, trans in translations:
                normalized_lang = lang.lower()  # 言語コードを小文字に正規化
                normalized_translations.add((normalized_lang, trans))
            self.translations[tag] = normalized_translations

        # usage_countsの重複削除
        # usage_countsは{(tag, format_id): count}の形式
        # キーが(tag, format_id)のタプルなので、重複は自動的に排除されている
        # 追加の処理は不要

        # tag_statusの整理と検証
        inconsistencies = []
        for (tag, format_id), (
            type_id,
            alias,
            preferred_tag,
        ) in self.tag_status.items():
            # エイリアスでないタグの preferred_tag が自身でない場合をチェック
            if not alias and preferred_tag != tag:
                inconsistencies.append(
                    f"Inconsistent tag status: {tag} (format_id: {format_id}) is not an alias but has preferred_tag {preferred_tag}"
                )
                # 自己参照に修正
                self.tag_status[(tag, format_id)] = (type_id, alias, tag)

            # エイリアスのタグの preferred_tag が存在するかチェック
            if alias and (preferred_tag, format_id) not in self.tag_status:
                inconsistencies.append(
                    f"Missing preferred tag: {preferred_tag} for alias {tag} (format_id: {format_id})"
                )
                # エイリアス状態を解除
                self.tag_status[(tag, format_id)] = (type_id, False, tag)

        # 不整合があった場合、ログに出力
        if inconsistencies:
            print("Inconsistencies found and corrected in tag_status:")
            for inc in inconsistencies:
                print(f"  - {inc}")

    def export_to_csv(self, output_dir: Path):
        """最終テーブル構造確認用のCSVファイルをエクスポートする

        Args:
            output_dir (Path): _description_
        """
        # クラス変数 データの重複を削除
        self.deduplicate_data()

        output_dir.mkdir(parents=True, exist_ok=True)

        # TAGSのエクスポート
        self._export_tags(output_dir / "tags.csv")

        # TRANSLATIONSのエクスポート
        self._export_translations(output_dir / "translations.csv")

        # USAGE COUNTSのエクスポート
        self._export_usage_counts(output_dir / "usage_counts.csv")

        # TAG STATUSのエクスポート
        self._export_tag_status(output_dir / "tag_status.csv")

        print(f"CSV files have been exported to {output_dir}")

    def _export_tags(self, file_path: Path):
        """
        タグ情報をCSVファイルにエクスポートするメソッド
        tag_idを含めて出力する

        Args:
            file_path (Path): 出力するCSVファイルのパス
        """
        with file_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["tag_id", "source_tag", "normalized_tag"])
            for tag_id, (source_tag, normalized_tag) in self.tags.items():
                writer.writerow([tag_id, source_tag, normalized_tag])

    def _export_translations(self, file_path: Path):
        with file_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["tag", "language", "translation"])
            for tag, translations in self.translations.items():
                for lang, trans in translations:
                    writer.writerow([tag, lang, trans])

    def _export_usage_counts(self, file_path: Path):
        with file_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["tag", "format_id", "count"])
            for (tag, format_id), count in self.usage_counts.items():
                writer.writerow([tag, format_id, count])

    def _export_tag_status(self, file_path: Path):
        with file_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["tag_id", "format_id", "type_id", "alias", "preferred_tag"]
            )
            for (tag_id, format_id), (
                type_id,
                alias,
                preferred_tag,
            ) in self.tag_status.items():
                writer.writerow([tag_id, format_id, type_id, int(alias), preferred_tag])

    def run(self, csv_dir: Path, output_dir: Path):
        print("CSVファイルの処理...")
        self.process_csv_files(csv_dir)
        self.export_to_csv(output_dir)
        print("Creating final tables...")
        print("最終テーブルの作成...")
        self.create_final_tables()
        print("最終テーブルへのデータの挿入...")
        self.insert_into_final_tables()
        print("Processing completed.")


# メイン処理
def main():
    db_path = Path("tags_v3.db")
    csv_dir = Path("tags")
    output_dir = Path("")
    processor = CSVToDatabaseProcessor(db_path)
    processor.run(csv_dir, output_dir)


if __name__ == "__main__":
    main()
