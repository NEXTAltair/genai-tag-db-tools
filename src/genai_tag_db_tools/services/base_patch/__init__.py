"""Base DB correction patch pipeline (issues #58 / #60 / #61).

This package implements the base DB correction-patch pipeline that sits between
approved refinement feedback (#57) and the dataset-builder:

- :mod:`validate` (#58): validate base DB correction patch JSONL before apply.
- :mod:`export` (#61): export approved refinement feedback to a base patch JSONL.
- :mod:`apply` (#60): apply validated patches to base DB build sources.

The base correction patch is a name-based, builder-friendly envelope. It is
intentionally separate from the overlay/id-based :class:`DbFeedbackProposal`
used for user-local apply (#59).
"""

from __future__ import annotations

from genai_tag_db_tools.services.base_patch.apply import (
    BasePatchApplyResult,
    BasePatchApplyRow,
    BasePatchApplyService,
    apply_base_patch_file,
)
from genai_tag_db_tools.services.base_patch.export import (
    BasePatchExportResult,
    BasePatchExportRow,
    export_base_patch_file,
    export_base_patches,
)
from genai_tag_db_tools.services.base_patch.models import (
    SCHEMA_VERSION,
    BaseCorrectionPatch,
    PatchValidationIssue,
    PatchValidationItemResult,
    PatchValidationResult,
    compute_patch_id,
)
from genai_tag_db_tools.services.base_patch.validate import (
    validate_base_patch,
    validate_base_patch_file,
)

__all__ = [
    "SCHEMA_VERSION",
    "BaseCorrectionPatch",
    "BasePatchApplyResult",
    "BasePatchApplyRow",
    "BasePatchApplyService",
    "BasePatchExportResult",
    "BasePatchExportRow",
    "PatchValidationIssue",
    "PatchValidationItemResult",
    "PatchValidationResult",
    "apply_base_patch_file",
    "compute_patch_id",
    "export_base_patch_file",
    "export_base_patches",
    "validate_base_patch",
    "validate_base_patch_file",
]
