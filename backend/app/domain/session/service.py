"""Application service tying the engine to the protocol renderer.

Kept in the domain layer so it can be exercised without FastAPI or a database,
which is what SDD section 7 requires of the recommendation path.
"""

from __future__ import annotations

from app.domain.practice.catalog import KnowledgeCatalog
from app.domain.recommendation.engine import Recommendation, RecommendationEngine
from app.domain.session.planner import SessionPlan, render_plan
from app.domain.state.models import CheckIn


def build_plan(
    catalog: KnowledgeCatalog, recommendation: Recommendation, *, title_from_practice: bool = True
) -> SessionPlan:
    protocol = catalog.protocol_for(recommendation.practice_id)
    title = None
    if title_from_practice:
        title = catalog.practice(recommendation.practice_id).public_name
    return render_plan(
        protocol,
        duration_minutes=recommendation.duration_minutes,
        guidance_density=recommendation.guidance_density,
        practice_public_title=title,
    )


def recommend_and_plan(
    engine: RecommendationEngine, check_in: CheckIn
) -> tuple[Recommendation, SessionPlan]:
    recommendation = engine.recommend(check_in)
    return recommendation, build_plan(engine.catalog, recommendation)
