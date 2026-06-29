# genai-tag-db-tools Makefile
# OKF ドキュメント検証・索引生成タスク (ADR 0010 / Issue #108)

.PHONY: help adr-okf adr-index docs-okf

OKF := .agents/skills/okf-bundle/scripts

# DOCS_OKF_EXCLUDE: frontmatter 規約の対象外 (README/メタ系 + 外部ツールが固有形式を要求する SKILL.md)。
DOCS_OKF_EXCLUDE := README.md,CHANGELOG.md,AGENTS.md,GEMINI.md,CLAUDE.md,SKILL.md

help:
	@echo "genai-tag-db-tools - OKF documentation targets:"
	@echo "  adr-okf      Validate ADR frontmatter (全件必須) + check index is up to date"
	@echo "  adr-index    Regenerate ADR index.md + README table from frontmatter"
	@echo "  docs-okf     Validate docs OKF frontmatter (lazy: --skip-missing)"

# ADR (OKF バンドル) の README テーブル + index.md を frontmatter から再生成する (ADR 0010)。
adr-index:
	@echo "Regenerating ADR index from frontmatter..."
	python3 $(OKF)/okf_index.py --bundle-root docs/decisions \
		--table --columns id,title,timestamp,status --headers "ADR,タイトル,日付,ステータス" \
		--link-column id --exclude README.md --table-output docs/decisions/README.md
	python3 $(OKF)/okf_index.py --bundle-root docs/decisions \
		--index --index-output docs/decisions/index.md \
		--index-title "Architecture Decision Records" --exclude README.md

# ADR の frontmatter を OKF 規約に照らして検証する (全件 frontmatter 必須、ADR 0010)。
adr-okf:
	@echo "Validating ADR frontmatter (OKF)..."
	python3 $(OKF)/okf_validate.py --bundle-root docs/decisions \
		--require type,title,status,timestamp --exclude README.md
	python3 $(OKF)/okf_index.py --bundle-root docs/decisions \
		--table --columns id,title,timestamp,status --headers "ADR,タイトル,日付,ステータス" \
		--link-column id --exclude README.md --table-output docs/decisions/README.md --check
	python3 $(OKF)/okf_index.py --bundle-root docs/decisions \
		--index --index-output docs/decisions/index.md \
		--index-title "Architecture Decision Records" --exclude README.md --check

# 通常ドキュメント (docs) の OKF frontmatter を検証する (ADR 0010)。
# lazy migration: --skip-missing で frontmatter 未付与ファイルは pass、付与済みのみ type/timestamp を検証。
docs-okf:
	@echo "Validating documentation OKF frontmatter (lazy migration, ADR 0010)..."
	python3 $(OKF)/okf_validate.py --bundle-root docs \
		--skip-missing --exclude $(DOCS_OKF_EXCLUDE)
