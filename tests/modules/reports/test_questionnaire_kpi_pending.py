"""Unit tests for command/action-center KPI pending rules."""

from __future__ import annotations

from modules.reports.questionnaire_kpi_completion import (
    KpiQuestionnaireData,
    rollup_questionnaire_kpi_for_engagement,
)


def test_kpi_rollup_partial_user_not_filled():
  data = KpiQuestionnaireData(
      pkg_categories={1: {"physical-measurement", "vitals"}},
      progress_map={
          10: {
              "physical-measurement": {"status": "incomplete", "completed_at": None},
              "vitals": {"status": "incomplete", "completed_at": None},
          }
      },
      resp_counts={10: 1},
      cat_resp_map={10: {"physical-measurement": True, "vitals": False}},
      unanswered_map={10: {"physical-measurement": [{"question_text": "Height"}]}},
  )
  rollup = rollup_questionnaire_kpi_for_engagement(
      scoped_users={100},
      instance_rows=[(10, 100, 1, 5, None)],
      data=data,
  )
  assert 100 not in rollup["filled_user_ids"]
  assert rollup["partially_filled"] == 1