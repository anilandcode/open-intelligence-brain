"""Tests for held-out evaluation and Hermes messaging."""

import pytest
from unittest.mock import patch, MagicMock
from brain.evaluation import (
    run_evaluation,
    evaluate_event,
    EvaluationReport,
    DEFAULT_TEST_EVENTS,
)
from brain.decision import DeterministicProvider, JevShadowProvider, DecisionSuggestion
from brain.messaging import HermesMessenger, HermesConfig


class TestEvaluation:
    def test_deterministic_vs_deterministic(self):
        """When both providers are deterministic, they always agree."""
        det = DeterministicProvider()
        verdict = evaluate_event(
            text="What is our churn rate?",
            channel="slack",
            addressed=True,
            deterministic=det,
            jev=det,
        )
        assert verdict.agrees is True

    def test_run_evaluation_with_deterministic_fallback(self):
        """Jev falls back to pass when unreachable — should still produce a report."""
        report = run_evaluation(jev_url="http://localhost:99999")
        assert isinstance(report, EvaluationReport)
        assert report.total_events == len(DEFAULT_TEST_EVENTS)
        assert report.agreement_rate >= 0.0
        assert len(report.summary) > 0

    def test_report_to_dict(self):
        report = run_evaluation(jev_url="http://localhost:99999")
        d = report.to_dict()
        assert "total_events" in d
        assert "agreement_rate" in d
        assert "disagreements" in d
        assert "summary" in d

    def test_custom_events(self):
        events = [
            {"text": "test question", "channel": "slack", "addressed": True},
        ]
        report = run_evaluation(jev_url="http://localhost:99999", events=events)
        assert report.total_events == 1

    def test_agreement_rate_bounds(self):
        report = run_evaluation(jev_url="http://localhost:99999")
        assert 0.0 <= report.agreement_rate <= 1.0


class TestMessaging:
    def test_config_from_env(self):
        config = HermesConfig.from_env()
        assert isinstance(config, HermesConfig)
        # Default: not configured
        assert config.configured is False or isinstance(config.api_url, str)

    def test_default_config(self):
        config = HermesConfig()
        assert config.configured is False
        assert config.channel == "digital-brain"

    def test_configured_config(self):
        config = HermesConfig(api_url="http://localhost:5177")
        assert config.configured is True

    def test_send_without_config_logs(self):
        messenger = HermesMessenger(HermesConfig())
        result = messenger.send("test message")
        assert result is False  # Not configured, logs instead

    def test_test_connection_without_config(self):
        messenger = HermesMessenger(HermesConfig())
        assert messenger.test_connection() is False

    def test_send_routine(self):
        messenger = HermesMessenger(HermesConfig())
        result = messenger.send_routine("test digest")
        assert result is False  # Not configured

    def test_send_alert(self):
        messenger = HermesMessenger(HermesConfig())
        result = messenger.send_alert("test alert")
        assert result is False  # Not configured