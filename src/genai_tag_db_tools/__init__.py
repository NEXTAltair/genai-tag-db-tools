"""genai-tag-db-tools package exports.

The names re-exported here form the **stable public API**. Downstream consumers
should import exclusively from this top-level package (or from
``genai_tag_db_tools.api`` / ``genai_tag_db_tools.models``) and must not depend on
internal modules such as ``genai_tag_db_tools.db.*`` or
``genai_tag_db_tools.services.*``.

Stable handles (opaque; use only for annotations): ``TagReaderProtocol``,
``TagRegisterServiceProtocol``, ``TagWriterProtocol``. Obtain instances via
``get_tag_reader`` / ``get_user_tag_reader`` / ``create_tag_register_service`` /
``get_user_repository`` and pass them to the module-level helpers.
"""

from .api import (
    TagReaderProtocol,
    TagRegisterServiceProtocol,
    TagWriterProtocol,
    create_tag_register_service,
    get_tag_reader,
    get_user_repository,
    get_user_tag_reader,
)
from .core_api import (
    build_downloaded_at_utc,
    convert_tags,
    ensure_databases,
    get_all_type_names,
    get_format_type_names,
    get_statistics,
    get_tag_formats,
    get_unknown_type_tags,
    initialize_databases,
    needs_manual_refinement,
    recommend_manual_refinement,
    recommend_tag_record_refinement,
    recommend_translation_quality,
    register_tag,
    search_tags,
    search_tags_batch,
    update_tags_type_batch,
    write_user_translation,
)
from .models import (
    ApprovedDbFeedback,
    DbFeedbackProposal,
    LocalFeedbackApplicationRecord,
    LocalFeedbackApplyResult,
    ProposalTarget,
    RefinementReason,
    RefinementRecommendation,
    RefinementSuggestion,
    TagTypeUpdate,
)
from .services.feedback_apply import apply_approved_feedback, list_local_feedback_applications
from .services.tag_search import TagSearcher
from .utils.cleanup_str import TagCleaner

# --- Backward-compatibility aliases -------------------------------------------
# These let existing callers migrate to the top-level package with a one-line
# import swap before adopting the new factory-based surface. They are intentional
# *stable type aliases* / factory aliases, not the internal implementation
# classes. Prefer the canonical names (TagReaderProtocol, get_tag_reader, ...).
MergedTagReader = TagReaderProtocol
get_default_reader = get_tag_reader

__all__ = [
    "ApprovedDbFeedback",
    "DbFeedbackProposal",
    "LocalFeedbackApplicationRecord",
    "LocalFeedbackApplyResult",
    "MergedTagReader",
    "ProposalTarget",
    "RefinementReason",
    "RefinementRecommendation",
    "RefinementSuggestion",
    "TagCleaner",
    "TagReaderProtocol",
    "TagRegisterServiceProtocol",
    "TagSearcher",
    "TagTypeUpdate",
    "TagWriterProtocol",
    "apply_approved_feedback",
    "build_downloaded_at_utc",
    "convert_tags",
    "create_tag_register_service",
    "ensure_databases",
    "get_all_type_names",
    "get_default_reader",
    "get_format_type_names",
    "get_statistics",
    "get_tag_formats",
    "get_tag_reader",
    "get_unknown_type_tags",
    "get_user_repository",
    "get_user_tag_reader",
    "initialize_databases",
    "initialize_tag_cleaner",
    "initialize_tag_searcher",
    "list_local_feedback_applications",
    "needs_manual_refinement",
    "recommend_manual_refinement",
    "recommend_tag_record_refinement",
    "recommend_translation_quality",
    "register_tag",
    "search_tags",
    "search_tags_batch",
    "update_tags_type_batch",
    "write_user_translation",
]


def initialize_tag_searcher() -> TagSearcher:
    """Return TagSearcher instance."""
    return TagSearcher()


def initialize_tag_cleaner() -> TagCleaner:
    """Return TagCleaner instance."""
    return TagCleaner()
