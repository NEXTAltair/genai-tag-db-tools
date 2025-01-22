from pathlib import Path
import sys

# プロジェクトのルートディレクトリをパスに追加(必要に応じて調整)
sys.path.insert(0, Path(__file__).parents[1].as_posix())

project = "genai-tag-db-tools"
author = "NEXTAltair"

# バージョン情報(必要に応じて記載)
version = "0.1.0"
release = "0.1.0"

# テーマや拡張の設定
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_rtd_theme",
]

# Napoleon設定(Googleスタイル、NumPyスタイルDocstring対応など)
napoleon_google_docstring = True
napoleon_numpy_docstring = True

templates_path = ["_templates"]
source_suffix = ".rst"
master_doc = "index"

# 言語設定
language = "ja"

# 静的ファイルパス
html_static_path = []

# テーマ設定
html_theme = "sphinx_rtd_theme"

# html_title設定(必要に応じて)
html_title = "genai-tag-db-tools ドキュメント"

# highlight設定等(必要に応じて)
pygments_style = "sphinx"
