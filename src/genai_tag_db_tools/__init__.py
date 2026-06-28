"""genai-tag-db-tools package exports."""

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
    update_tags_type_batch,
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

__all__ = [
    "ApprovedDbFeedback",
    "DbFeedbackProposal",
    "LocalFeedbackApplicationRecord",
    "LocalFeedbackApplyResult",
    "ProposalTarget",
    "RefinementReason",
    "RefinementRecommendation",
    "RefinementSuggestion",
    "TagCleaner",
    "TagSearcher",
    "TagTypeUpdate",
    "apply_approved_feedback",
    "build_downloaded_at_utc",
    "convert_tags",
    "ensure_databases",
    "get_all_type_names",
    "get_format_type_names",
    "get_statistics",
    "get_tag_formats",
    "get_unknown_type_tags",
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
    "update_tags_type_batch",
]


def initialize_tag_searcher() -> TagSearcher:
    """Return TagSearcher instance."""
    return TagSearcher()


def initialize_tag_cleaner() -> TagCleaner:
    """Return TagCleaner instance."""
    return TagCleaner()
