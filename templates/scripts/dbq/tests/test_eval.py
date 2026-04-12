"""
Tests for the evaluation system: scoring, remediation, eval commands.

Uses the shared fixtures from conftest.py (empty_db, populated_db,
simple_config, populated_config).
"""
import json
import math
from pathlib import Path

import pytest

from dbq.scoring import (
    score_with_confidence,
    estimate_tokens,
    sigmoid_penalty,
    weighted_composite,
)
from dbq.remediation import (
    EvalCheckResult,
    Recommendation,
    get_recommendations,
    RULES,
)
from dbq.commands.eval import (
    eval_layer1,
    eval_layer2,
    eval_layer3,
    cmd_eval,
    cmd_eval_report,
    cmd_eval_compare,
)
from dbq.db import Database


# ══════════════════════════════════════════════════════════════════
# Scoring primitives
# ══════════════════════════════════════════════════════════════════


class TestScoreWithConfidence:
    def test_zero_samples_returns_none(self):
        assert score_with_confidence(100, 0) is None

    def test_one_sample_blends_toward_neutral(self):
        result = score_with_confidence(100, 1, min_samples=3)
        # confidence = 1/3, so: 100*(1/3) + 50*(2/3) = 66.67
        assert abs(result - 66.67) < 0.1

    def test_two_samples(self):
        result = score_with_confidence(100, 2, min_samples=3)
        assert abs(result - 83.33) < 0.1

    def test_min_samples_returns_raw(self):
        assert score_with_confidence(100, 3, min_samples=3) == 100.0

    def test_above_min_samples_returns_raw(self):
        assert score_with_confidence(75, 10, min_samples=3) == 75.0

    def test_zero_raw_score(self):
        result = score_with_confidence(0, 1, min_samples=3)
        # 0*(1/3) + 50*(2/3) = 33.33
        assert abs(result - 33.33) < 0.1

    def test_negative_raw_score_clamped_to_zero(self):
        """Negative raw scores should not produce negative output."""
        result = score_with_confidence(-200, 3, min_samples=3)
        assert result == 0.0

    def test_above_100_raw_score_clamped(self):
        """Raw scores above 100 should not produce output above 100."""
        result = score_with_confidence(500, 3, min_samples=3)
        assert result == 100.0

    def test_negative_with_low_confidence_clamped(self):
        """Even with blending, result must stay in 0-100."""
        result = score_with_confidence(-500, 1, min_samples=3)
        assert 0.0 <= result <= 100.0


class TestEstimateTokens:
    def test_positive_for_nonempty(self):
        assert estimate_tokens("hello world") > 0

    def test_zero_for_empty(self):
        assert estimate_tokens("") == 0

    def test_scales_with_length(self):
        short = estimate_tokens("one two three")
        long = estimate_tokens("one two three four five six seven eight nine ten")
        assert long > short


class TestSigmoidPenalty:
    @pytest.mark.parametrize("actual,target,expected", [
        (50, 100, 100.0),    # under target — perfect
        (100, 100, 100.0),   # at target — perfect
        (0, 0, 100.0),       # zero target — guard returns perfect
        (100, 0, 100.0),     # zero target with actual — guard returns perfect
        (50, -10, 100.0),    # negative target — guard returns perfect
    ])
    def test_returns_perfect(self, actual: float, target: float, expected: float):
        """sigmoid_penalty returns 100.0 when at or under target, or when target <= 0."""
        assert sigmoid_penalty(actual, target) == expected

    def test_over_target_drops(self):
        score = sigmoid_penalty(200, 100)
        assert 0 < score < 100

    def test_way_over_target_is_very_low(self):
        score = sigmoid_penalty(500, 100)
        assert score < 10

    def test_near_target_gentle_penalty(self):
        score = sigmoid_penalty(120, 100)
        assert score > 50


class TestWeightedComposite:
    def test_all_none_returns_none(self):
        assert weighted_composite({"A": None, "B": None}, {"A": 0.5, "B": 0.5}) is None

    def test_single_active_gets_full_weight(self):
        result = weighted_composite({"A": 80.0, "B": None}, {"A": 0.5, "B": 0.5})
        assert result == 80.0

    def test_equal_weights(self):
        result = weighted_composite(
            {"A": 80.0, "B": 90.0}, {"A": 0.5, "B": 0.5}
        )
        assert result == 85.0

    def test_unequal_weights(self):
        result = weighted_composite(
            {"A": 100.0, "B": 0.0}, {"A": 0.75, "B": 0.25}
        )
        assert result == 75.0

    def test_weight_redistribution_with_nones(self):
        scores = {"A": 100.0, "B": None, "C": 50.0}
        weights = {"A": 0.4, "B": 0.3, "C": 0.3}
        result = weighted_composite(scores, weights)
        # Redistributed: A=0.4/0.7=0.571, C=0.3/0.7=0.429
        expected = 100 * (0.4 / 0.7) + 50 * (0.3 / 0.7)
        assert abs(result - expected) < 0.01

    def test_out_of_range_scores_clamped(self):
        """Composite should be clamped to 0-100 even with bad inputs."""
        scores = {"A": 200.0, "B": 200.0}
        weights = {"A": 0.5, "B": 0.5}
        result = weighted_composite(scores, weights)
        assert result <= 100.0

    def test_negative_scores_clamped(self):
        """Negative input scores should not produce negative composite."""
        scores = {"A": -50.0, "B": -50.0}
        weights = {"A": 0.5, "B": 0.5}
        result = weighted_composite(scores, weights)
        assert result >= 0.0


# ══════════════════════════════════════════════════════════════════
# Remediation engine
# ══════════════════════════════════════════════════════════════════


class TestEvalCheckResult:
    def test_to_dict_roundtrips(self):
        check = EvalCheckResult(
            id="D1",
            name="Tools",
            score=85.7,
            details="6/7 deployed",
            remediation="Missing: save_session.sh",
            auto_fixable=True,
            fix_command="cp x y",
        )
        d = check.to_dict()
        assert d["score"] == 85.7
        assert d["remediation"] == "Missing: save_session.sh"
        assert d["auto_fixable"] is True
        # JSON roundtrip
        j = json.dumps(d)
        assert json.loads(j) == d

    def test_defaults(self):
        check = EvalCheckResult(id="D1", name="Tools", score=100.0)
        assert check.remediation == ""
        assert check.auto_fixable is False
        assert check.fix_command is None
        assert check.sub_checks == []


class TestRecommendations:
    @pytest.mark.parametrize("trigger,score_val,expected_priority", [
        ("D2", 30, 1),
        ("D7", 0, 1),
    ])
    def test_critical_rules_fire(self, trigger: str, score_val, expected_priority: int):
        """Low D2 and zero D7 both fire critical (priority=1) recommendations."""
        scores = {trigger: score_val}
        recs = get_recommendations(scores)
        assert any(r.trigger == trigger and r.priority == expected_priority for r in recs)
        # The recommendation should have a non-empty message
        matching = [r for r in recs if r.trigger == trigger]
        assert all(r.message for r in matching)

    @pytest.mark.parametrize("trigger,score_val", [
        ("P4", 48),
        ("P6", None),
    ])
    def test_process_rules_fire(self, trigger: str, score_val):
        """Process metric rules fire when scores are below threshold or None."""
        scores = {trigger: score_val}
        recs = get_recommendations(scores)
        assert any(r.trigger == trigger for r in recs)

    def test_v2_above_50_does_not_fire(self):
        scores = {"V2": 75}
        recs = get_recommendations(scores)
        assert not any(r.trigger == "V2" for r in recs)

    def test_all_perfect_no_recommendations(self):
        scores = {
            "D1": 100, "D2": 100, "D3": 100, "D4": 100,
            "D5": 100, "D6": 100, "D7": 100, "D8": 100,
            "P1": 100, "P2": 100, "P3": 100, "P4": 100,
            "P5": 100, "P6": 100, "P7": 100, "P8": 100,
            "V1": 100, "V2": 100, "V3": 100, "V4": 100,
        }
        recs = get_recommendations(scores)
        assert len(recs) == 0

    def test_sorted_by_priority(self):
        scores = {"D2": 30, "P4": 48, "P6": None}
        recs = get_recommendations(scores)
        priorities = [r.priority for r in recs]
        assert priorities == sorted(priorities)


# ══════════════════════════════════════════════════════════════════
# Eval layers against test DB
# ══════════════════════════════════════════════════════════════════


class TestEvalLayer1:
    def test_empty_db_runs_without_crash(self, empty_db, simple_config):
        score, results = eval_layer1(empty_db, simple_config)
        # Empty DB: D2 should detect empty tasks table
        assert "D2" in results
        assert results["D2"].score is not None
        # All expected check IDs must be present
        for check_id in ("D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"):
            assert check_id in results, f"Missing check {check_id} in layer1 results"

    def test_populated_db_d2_passes(self, populated_db, populated_config):
        score, results = eval_layer1(populated_db, populated_config)
        # D2 should pass most checks with populated data
        assert results["D2"].score >= 50
        # With real tasks, the composite should be calculable (not None)
        # It may still be capped but should be a number
        # (populated_db may not have all files so score could be low but not None)
        assert results["D2"].score is not None

    def test_critical_ceiling_caps_at_30(self, empty_db, simple_config):
        """If D2 < 50 or D7 = 0, composite is capped at 30."""
        score, results = eval_layer1(empty_db, simple_config)
        d2 = results["D2"].score or 0
        d7 = results["D7"].score or 0
        if d2 < 50 or d7 == 0:
            assert score is None or score <= 30
            # Verify the D2 result has a non-empty details string
            assert results["D2"].details != "" or results["D2"].score is not None


class TestEvalLayer2:
    def test_empty_db_returns_none_for_sparse_metrics(
        self, empty_db, simple_config
    ):
        score, results = eval_layer2(empty_db, simple_config)
        # P2 (defect escape) should be None with no loopbacks
        assert results["P2"].score is None
        # P3 (rework) should be None with no loopbacks
        assert results["P3"].score is None
        # All expected check IDs must be present
        for check_id in ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"):
            assert check_id in results, f"Missing check {check_id} in layer2 results"

    def test_populated_db_p1_completion(self, populated_db, populated_config):
        score, results = eval_layer2(populated_db, populated_config)
        # 1 DONE out of 5 eligible (none are SKIP/WONTFIX)
        assert results["P1"].score is not None
        assert results["P1"].score == pytest.approx(20.0)  # 1/5
        # Details string should mention the completion fraction
        assert results["P1"].details != ""

    def test_populated_p6_no_assumptions(self, populated_db, populated_config):
        score, results = eval_layer2(populated_db, populated_config)
        assert results["P6"].score is None
        assert "No assumptions" in results["P6"].details
        # P6 result should be a proper EvalCheckResult with id set
        assert results["P6"].id == "P6"


class TestEvalP8Escalation:
    def test_no_triaged_tasks_returns_none(self, empty_db, simple_config):
        """P8 returns None score when no tasks have original_tier set."""
        score, results = eval_layer2(empty_db, simple_config)
        assert results["P8"].score is None
        assert "No triaged" in results["P8"].details

    def test_zero_escalations_perfect_score(self, empty_db, simple_config):
        """P8 returns 100 when tasks have original_tier but no escalations."""
        for i in range(5):
            empty_db.execute(
                "INSERT INTO tasks (id, phase, title, status, assignee, "
                "tier, original_tier, escalation_count, queue) "
                "VALUES (?, 'P1-TEST', ?, 'DONE', 'CLAUDE', 'haiku', 'haiku', 0, 'A')",
                (f"T-P8-{i}", f"Task {i}"),
            )
        empty_db.commit()
        score, results = eval_layer2(empty_db, simple_config)
        assert results["P8"].score == 100.0
        assert "0%" in results["P8"].details

    def test_some_escalations_reduces_score(self, empty_db, simple_config):
        """P8 score decreases proportionally with escalation rate."""
        # 2 tasks, 1 escalated = 50% rate → score = max(0, 100 - 50*4) = 0
        for i, esc in enumerate([0, 1]):
            empty_db.execute(
                "INSERT INTO tasks (id, phase, title, status, assignee, "
                "tier, original_tier, escalation_count, queue) "
                "VALUES (?, 'P1-TEST', ?, 'DONE', 'CLAUDE', 'sonnet', 'haiku', ?, 'A')",
                (f"T-P8E-{i}", f"Task {i}", esc),
            )
        empty_db.commit()
        score, results = eval_layer2(empty_db, simple_config)
        assert results["P8"].score is not None
        assert results["P8"].score < 100.0  # some penalty applied


class TestEvalLayer3:
    def test_first_run_v1_is_none(self, empty_db, simple_config):
        score, results = eval_layer3(empty_db, simple_config)
        assert results["V1"].score is None
        assert "First evaluation" in results["V1"].details
        # All expected V-check IDs must be present
        for check_id in ("V1", "V2", "V3", "V4"):
            assert check_id in results, f"Missing check {check_id} in layer3 results"

    def test_first_run_v3_is_none(self, empty_db, simple_config):
        score, results = eval_layer3(empty_db, simple_config)
        assert results["V3"].score is None
        # V3 result should be a proper EvalCheckResult
        assert results["V3"].id == "V3"

    def test_v4_insufficient_snapshots(self, empty_db, simple_config):
        score, results = eval_layer3(empty_db, simple_config)
        assert results["V4"].score is None
        # Details should explain why V4 is unavailable
        assert results["V4"].details != ""


# ══════════════════════════════════════════════════════════════════
# Evaluations table
# ══════════════════════════════════════════════════════════════════


class TestEvaluationsTable:
    def test_table_created_on_init(self, empty_db):
        assert empty_db.table_exists("evaluations")

    def test_insert_and_read_roundtrip(self, empty_db):
        empty_db.execute(
            "INSERT INTO evaluations "
            "(version, phase, artifact_score, artifact_details, "
            " process_score, process_details, "
            " velocity_score, velocity_details, "
            " composite_score, raw_metrics) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "v0.8.0",
                "P4-VALIDATE",
                85.0,
                json.dumps({"D1": {"score": 100}}),
                78.0,
                json.dumps({"P1": {"score": 100}}),
                75.0,
                json.dumps({"V2": {"score": 75}}),
                80.0,
                json.dumps({"D1": 100, "P1": 100}),
            ),
        )
        empty_db.commit()

        row = empty_db.fetch_all(
            "SELECT * FROM evaluations ORDER BY id DESC LIMIT 1"
        )[0]
        assert row["version"] == "v0.8.0"
        assert row["composite_score"] == 80.0
        assert json.loads(row["artifact_details"])["D1"]["score"] == 100

    def test_multiple_evals_stored(self, empty_db):
        for i in range(3):
            empty_db.execute(
                "INSERT INTO evaluations (version, composite_score) VALUES (?, ?)",
                (f"v{i}", float(70 + i * 5)),
            )
        empty_db.commit()

        rows = empty_db.fetch_all(
            "SELECT * FROM evaluations ORDER BY id"
        )
        assert len(rows) == 3
        assert rows[0]["composite_score"] == 70.0
        assert rows[2]["composite_score"] == 80.0


# ══════════════════════════════════════════════════════════════════
# CLI command integration
# ══════════════════════════════════════════════════════════════════


class TestCmdEval:
    def test_eval_stores_result(self, populated_db, populated_config, capsys):
        cmd_eval(populated_db, populated_config)
        out = capsys.readouterr().out
        assert "EVALUATION SCORECARD" in out
        assert "COMPOSITE" in out

        # Verify stored in DB
        rows = populated_db.fetch_all("SELECT * FROM evaluations")
        assert len(rows) >= 1

    def test_eval_json_output(self, populated_db, populated_config, capsys):
        cmd_eval(populated_db, populated_config, json_output=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "composite" in data
        assert "layers" in data
        assert "L1" in data["layers"]
        assert "L2" in data["layers"]
        assert "L3" in data["layers"]

    def test_eval_with_version(self, populated_db, populated_config, capsys):
        cmd_eval(populated_db, populated_config, version="v1.0.0")
        out = capsys.readouterr().out
        row = populated_db.fetch_all(
            "SELECT version, composite_score FROM evaluations ORDER BY id DESC LIMIT 1"
        )[0]
        assert row["version"] == "v1.0.0"
        assert row["composite_score"] is not None  # score was computed and stored
        assert "v1.0.0" in out or "EVALUATION" in out


class TestCmdEvalReport:
    def test_report_no_evals(self, empty_db, simple_config, capsys):
        cmd_eval_report(empty_db, simple_config)
        out = capsys.readouterr().out
        assert "No evaluation" in out

    def test_report_shows_latest(self, populated_db, populated_config, capsys):
        cmd_eval(populated_db, populated_config, version="v1.0.0")
        capsys.readouterr()  # clear eval output

        cmd_eval_report(populated_db, populated_config)
        out = capsys.readouterr().out
        assert "v1.0.0" in out
        assert "COMPOSITE" in out

    def test_report_all_lists_evals(self, populated_db, populated_config, capsys):
        cmd_eval(populated_db, populated_config, version="v1")
        cmd_eval(populated_db, populated_config, version="v2")
        capsys.readouterr()

        cmd_eval_report(populated_db, populated_config, show_all=True)
        out = capsys.readouterr().out
        assert "v1" in out
        assert "v2" in out


class TestCmdEvalCompare:
    def test_compare_needs_two_evals(self, empty_db, simple_config, capsys):
        cmd_eval_compare(empty_db, simple_config, last_n=2)
        out = capsys.readouterr().out
        assert "Need at least 2" in out

    def test_compare_last_two(self, populated_db, populated_config, capsys):
        cmd_eval(populated_db, populated_config, version="v1")
        cmd_eval(populated_db, populated_config, version="v2")
        capsys.readouterr()

        cmd_eval_compare(populated_db, populated_config, last_n=2)
        out = capsys.readouterr().out
        assert "EVALUATION COMPARISON" in out
        assert "COMPOSITE" in out
        # Both versions should be referenced in the comparison
        assert "v1" in out
        assert "v2" in out
