#!/usr/bin/env bash

#=========================================================
# 移動前に以下を確認してください:
# 1. 作業ツリーがクリーンである (git status が何もない)
# 2. 既にコミットしてある (念のため変更をコミット済み)
# 3. スクリプト内のパスが正しいかどうか
#=========================================================

set -e  # エラーで停止
set -x  # デバッグログ表示（動作内容を表示）

# 例: ディレクトリ移動先の作成
# core/ -> db/ + services/
mkdir -p genai_tag_db_tools/db
mkdir -p genai_tag_db_tools/services

#--------------------------------------------------------
# 1) core/ 内の DB関連ファイルを db/ に移動 (例)
#--------------------------------------------------------
if [ -f genai_tag_db_tools/core/db_maintenance_tool.py ]; then
  git mv genai_tag_db_tools/core/db_maintenance_tool.py genai_tag_db_tools/db/
fi

if [ -f genai_tag_db_tools/core/import_data.py ]; then
  # import_data が「DBへの書き込み」がメインなら db/ かもしれませんが、
  # "ビジネスロジック" なら services/ へ移すことも多いです。
  # 以下例では "services/" に移動。
  git mv genai_tag_db_tools/core/import_data.py genai_tag_db_tools/services/
fi

# もし以下のようなファイルがあれば、用途に応じて移動先を決定
#   processor.py   => services/ (ビジネスロジック)
#   tag_search.py  => services/ (検索ロジック)
#   ...
if [ -f genai_tag_db_tools/core/processor.py ]; then
  git mv genai_tag_db_tools/core/processor.py genai_tag_db_tools/services/
fi

if [ -f genai_tag_db_tools/core/tag_search.py ]; then
  git mv genai_tag_db_tools/core/tag_search.py genai_tag_db_tools/services/
fi

# core/ ディレクトリが空になったら削除（git管理から外す）
if [ -d genai_tag_db_tools/core ]; then
  # 空ディレクトリなら削除
  rmdir genai_tag_db_tools/core 2>/dev/null || true
fi


#--------------------------------------------------------
# 2) .gitignore を更新
#    __pycache__/ や *.pyc, *.db を無視リストに加える
#--------------------------------------------------------
GITIGNORE_FILE=.gitignore

# まだ .gitignore が無ければ作成
if [ ! -f "$GITIGNORE_FILE" ]; then
  touch "$GITIGNORE_FILE"
fi

# 以下のパターンを追加 (重複しないよう注意)
#   - __pycache__/
#   - *.pyc
#   - *.db  (必要に応じて細かく指定する)
#   - *.db.*  (backup拡張子がついている場合用)
#   - *.sqlite など
#   ...
IGNORE_PATTERNS=(
"__pycache__/"
"*.pyc"
"*.db"
"*.db.*"
)

for pattern in "${IGNORE_PATTERNS[@]}"; do
  if ! grep -qxF "$pattern" "$GITIGNORE_FILE"; then
    echo "$pattern" >> "$GITIGNORE_FILE"
  fi
done


#--------------------------------------------------------
# 3) 既に存在する __pycache__ や .pyc, .db を管理から外す (任意)
#    ※ これをすると、コミット履歴上にある分は残りますが、
#       今後のコミットには含まれなくなります。
#--------------------------------------------------------
# （既にステージされている __pycache__ や *.pyc, *.db をアンステージし、削除扱いにする）
git rm -r --cached --ignore-unmatch **/__pycache__ || true
git rm --cached --ignore-unmatch **/*.pyc || true
git rm --cached --ignore-unmatch **/*.db || true
git rm --cached --ignore-unmatch **/*.db.* || true


#--------------------------------------------------------
# 4) 移動完了後、コミットメッセージを付けてコミット
#--------------------------------------------------------
git commit -m "Refactor: Move core files into db/ or services/, update .gitignore, remove caches"
