"""
duplicate_file_remover_ja.py

このスクリプトは指定されたディレクトリ内の重複ファイルを検出し、オプションで削除するためのものです。
Pathオブジェクトを使用してファイルシステム操作を行います。

使用方法:
    python duplicate_file_remover_ja.py

機能:
    1. ユーザーに対象ディレクトリのパスを入力させる
    2. 指定されたディレクトリ内のすべてのファイルをスキャンする
    3. MD5ハッシュを使用して重複ファイルを検出する
    4. 検出された重複ファイルのリストを表示する
    5. ユーザーに重複ファイルの削除オプションを提供する

依存パッケージ:
    - pathlib
    - hashlib
    - collections

注意:
    - このスクリプトは、ファイルの内容に基づいて重複を検出します
    - 重複ファイルの削除は慎重に行ってください。重要なファイルが失われる可能性があります
"""

import hashlib
from collections import defaultdict
from pathlib import Path


def get_file_hash(file_path):
    """ファイルのMD5ハッシュを計算する。"""
    hash_md5 = hashlib.md5()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def find_duplicate_files(directory):
    """指定されたディレクトリ内の重複ファイルを見つける。"""
    file_hash_dict = defaultdict(list)
    for file_path in Path(directory).rglob("*"):
        if file_path.is_file():
            file_hash = get_file_hash(file_path)
            file_hash_dict[file_hash].append(file_path)
    return {k: v for k, v in file_hash_dict.items() if len(v) > 1}


def remove_duplicates(duplicates):
    """重複ファイルを削除する。各グループの最初のファイルは保持される。"""
    for file_list in duplicates.values():
        for file_path in file_list[1:]:
            file_path.unlink()
            print(f"削除されました: {file_path}")


def main():
    directory = Path(input("重複ファイルを検索するディレクトリのパスを入力してください: "))
    if not directory.is_dir():
        print("無効なディレクトリパスです。")
        return

    duplicates = find_duplicate_files(directory)

    if not duplicates:
        print("重複ファイルは見つかりませんでした。")
        return

    print("重複ファイルが見つかりました:")
    for hash_value, file_list in duplicates.items():
        print(f"\nハッシュ {hash_value} を持つファイル:")
        for file_path in file_list:
            print(f"  {file_path}")

    choice = input("重複ファイルを削除しますか？ (y/n): ")
    if choice.lower() == "y":
        remove_duplicates(duplicates)
        print("重複ファイルの削除が完了しました。")
    else:
        print("重複ファイルは削除されませんでした。")


if __name__ == "__main__":
    main()
