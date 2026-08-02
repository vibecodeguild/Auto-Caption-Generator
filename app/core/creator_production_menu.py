"""Holdover helpers for the Creator Production multi-agent path only.

Not part of the product engine / usage / placement model. Does not read the
Graphics Library production set and does not assign or place graphics.
Density helpers are pure pacing math for legacy Creator Production plan checks.
"""

from __future__ import annotations

from pathlib import Path

from app.core.creator_production import ARTIFACT_SCHEMA_VERSION


def planning_capability_ids_for_profile(
    catalog: dict,
    channel_profile: dict | None,
) -> list[str]:
    """Capability ids a Creator Production planning agent may consider.

    Catalog + preferred list only. Not Graphics Library selection.
    """

    native = [
        item["id"]
        for item in catalog["capabilities"]
        if item.get("scope") == "blueprint-macro"
        and item.get("category") != "workflow-specific-transition-source"
    ]
    if not channel_profile:
        return native
    preferred = [
        str(item)
        for item in (channel_profile.get("capabilities") or {}).get("preferred") or []
        if str(item).strip()
    ]
    selection = channel_profile.get("selection") or {}
    full_catalog = bool(selection.get("fullCatalogEvaluationRequired"))
    available = {item["id"] for item in catalog["capabilities"]}
    if preferred:
        rest = [item for item in native if item not in preferred] if full_catalog else []
        return [item for item in preferred if item in available] + rest
    return native


def scrub_retired_catalog_rows(catalog: dict) -> dict:
    """No-op. Kept so Creator Production inventory call sites stay stable."""

    return catalog


def vcg_density_enabled(channel_profile: dict | None) -> bool:
    """True when density gates should run (profile pacing sets a max gap)."""

    if not channel_profile:
        return False
    return bool(
        (channel_profile.get("pacing") or {}).get("maximumMeaningfulChangeGapSec")
    )


def _fps_ratio(fps: dict) -> float:
    return float(fps["numerator"]) / max(float(fps["denominator"]), 1.0)


def density_errors(
    *,
    verified_change_frames: list[int],
    verified_carries: list[dict],
    total_frames: int,
    fps: dict,
    channel_profile: dict,
    authored_emphasis_frames: list[int] | None = None,
    spoken_word_frames: list[int] | None = None,
) -> list[dict]:
    """Reject sparse Creator Production plans (pacing only)."""

    del spoken_word_frames
    if total_frames <= 0:
        return []
    pacing = channel_profile.get("pacing") or {}
    max_gap_sec = float(pacing.get("maximumMeaningfulChangeGapSec") or 5)
    max_carry_sec = float(
        pacing.get("maximumContinuousCarrySec")
        or pacing.get("maximumPureSourceHoldSec")
        or 45
    )
    max_gap = max(1, round(max_gap_sec * _fps_ratio(fps)))
    max_carry = max(max_gap, round(max_carry_sec * _fps_ratio(fps)))
    errors: list[dict] = []

    change_frames = sorted(
        {
            int(frame)
            for frame in list(verified_change_frames or [])
            + list(authored_emphasis_frames or [])
            if int(frame) >= 0
        }
    )
    min_moments = max(1, int((total_frames + max_gap - 1) // max_gap))
    if len(change_frames) < min_moments:
        errors.append(
            {
                "code": "under-dense-visual-plan-count",
                "message": (
                    f"Plan has {len(change_frames)} visual moment(s); need at least "
                    f"{min_moments} for a {max_gap_sec:.0f}s density budget."
                ),
                "momentCount": len(change_frames),
                "minimumMoments": min_moments,
            }
        )

    cursor = 0
    for frame in change_frames:
        if frame - cursor > max_gap:
            errors.append(
                {
                    "code": "under-dense-visual-plan",
                    "message": (
                        f"Visual gap of {(frame - cursor) / _fps_ratio(fps):.1f}s exceeds "
                        f"{max_gap_sec:.0f}s maximum."
                    ),
                    "absoluteStartFrame": cursor,
                    "absoluteEndFrameExclusive": frame,
                }
            )
        cursor = max(cursor, frame)
    if total_frames - cursor > max_gap:
        errors.append(
            {
                "code": "under-dense-visual-plan",
                "message": (
                    f"Trailing visual gap of {(total_frames - cursor) / _fps_ratio(fps):.1f}s "
                    f"exceeds {max_gap_sec:.0f}s maximum."
                ),
                "absoluteStartFrame": cursor,
                "absoluteEndFrameExclusive": total_frames,
            }
        )

    for carry in verified_carries or []:
        start = int(carry.get("absoluteStartFrame") or 0)
        end = int(carry.get("absoluteEndFrameExclusive") or start)
        length = max(0, end - start)
        if length <= max_carry:
            continue
        has_emphasis = any(start <= frame < end for frame in change_frames)
        if not has_emphasis:
            errors.append(
                {
                    "code": "carry-without-emphasis-too-long",
                    "message": (
                        f"Carry of {length / _fps_ratio(fps):.1f}s exceeds "
                        f"{max_carry_sec:.0f}s without an emphasis checkpoint."
                    ),
                    "absoluteStartFrame": start,
                    "absoluteEndFrameExclusive": end,
                }
            )
    return errors


def resolve_library_implementation_path(
    *,
    catalog: dict | None = None,
    capability_id: str | None = None,
    adaptation_id: str | None = None,
    implementation_source_hash: str | None = None,
) -> Path | None:
    """Creator Production admitted implementations live under private project roots only."""

    del catalog, capability_id, adaptation_id, implementation_source_hash
    return None


_ = ARTIFACT_SCHEMA_VERSION
