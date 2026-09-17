"""Camp Report Intelligence Engine — public API.

``intelligence_src/`` is the maintained source. ``camp_intelligence_engine.py``
is a flattened snapshot and is not imported at runtime.
"""

from .intelligence_src.assembly import (
    INTELLIGENCE_CAMP_SECTIONS,
    LEADERSHIP_TAKEAWAYS_SECTION,
    enrich_camp_report_with_intelligence,
    generate_camp_section_intelligence,
    resolve_intelligence_section,
)
from .intelligence_src.engine import generate_report_insights

CAMP_INTELLIGENCE_INTERNAL_ENDPOINT = "internal://camp_report_intelligence/enrich"

__all__ = [
    "INTELLIGENCE_CAMP_SECTIONS",
    "LEADERSHIP_TAKEAWAYS_SECTION",
    "enrich_camp_report_with_intelligence",
    "generate_camp_section_intelligence",
    "generate_report_insights",
    "resolve_intelligence_section",
    "CAMP_INTELLIGENCE_INTERNAL_ENDPOINT",
]
