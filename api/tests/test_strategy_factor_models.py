import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Text

from app.models import Base
from app.research_factors import FACTORS, STRATEGIES
from app.strategy_workbench import _candidate


def test_factor_and_strategy_tables_replace_algorithm_version_storage():
    tables = Base.metadata.tables

    assert {
        "research_factors",
        "research_strategy_factors",
        "instrument_sentiment_links",
        "instrument_strategy_assignments",
        "strategy_comparisons",
        "strategy_comparison_factors",
        "strategy_signals",
        "strategy_execution_links",
        "market_fear_greed_daily",
        "market_regime_factor_daily",
        "research_strategy_scopes",
    } <= tables.keys()
    assert not {
        "saved_strategies",
        "saved_strategy_versions",
        "strategy_observations",
        "strategy_research_batches",
    } & tables.keys()
    assert set(tables["research_factors"].primary_key.columns.keys()) == {"factor_id"}
    assert set(tables["instrument_strategy_assignments"].primary_key.columns.keys()) == {"assignment_id"}
    assert "assignment_id" in tables["strategy_signals"].c
    assert "factor_id" in tables["strategy_comparison_factors"].c
    assert "research_strategies" not in tables
    assert set(STRATEGIES) == {
        "range_breakout_research",
        "left_reversal_research",
    }
    assert all(meta.get("research_only") for meta in STRATEGIES.values())
    for sid in (
        "range_breakout",
        "bottom_confirmation",
        "hybrid_reversal",
        "trend_pullback",
        "volatility_contraction_breakout",
        "value_sentiment_reversal",
        "gem_bottom_contraction",
    ):
        with pytest.raises(HTTPException, match="策略不可用"):
            _candidate(sid, "510300", allow_unadoptable=True)


def test_research_factor_directory_has_matching_database_columns_and_comments():
    factor_table = Base.metadata.tables["research_factors"]
    relation_table = Base.metadata.tables["research_strategy_factors"]
    sentiment_link_table = Base.metadata.tables["instrument_sentiment_links"]
    scope_table = Base.metadata.tables["research_strategy_scopes"]
    instruments_table = Base.metadata.tables["instruments"]

    assert set(FACTORS)  # Registry contains the complete first research set.
    assert "oversold_recovery" in FACTORS
    assert "close_above_prior_high" in FACTORS
    assert factor_table.comment and all(column.comment for column in factor_table.columns)
    assert relation_table.comment and all(column.comment for column in relation_table.columns)
    assert sentiment_link_table.comment and all(
        column.comment for column in sentiment_link_table.columns
    )
    assert scope_table.comment and all(column.comment for column in scope_table.columns)
    assert instruments_table.c.research_category.comment
    assert set(sentiment_link_table.primary_key.columns.keys()) == {
        "instrument_code",
        "category_key",
    }
    assert isinstance(sentiment_link_table.c.mapping_evidence.type, Text)
    assert "ix_instrument_sentiment_links_category_key" in {
        index.name for index in sentiment_link_table.indexes
    }
    assert all({factor_id for factor_id, _ in strategy["factors"]} <= set(FACTORS) for strategy in STRATEGIES.values())
    assert {
        "market_fear_extreme",
        "market_greed_extreme",
        "market_ivix_high",
        "market_ivix_calm",
        "market_breadth_weak",
        "market_futures_deep_discount",
    } <= set(FACTORS)


def test_legacy_overfit_multifactor_is_not_a_current_strategy():
    with pytest.raises(HTTPException, match="策略不可用"):
        _candidate("etf_multifactor", "510300")


def test_strategy_comparison_request_uses_strategy_identities_only():
    from app.strategy_workbench import ComparisonRequest

    request = ComparisonRequest.model_validate({
        "instrument_code": "510300",
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "strategies": ["range_breakout"],
    })
    assert request.strategies == ["range_breakout"]
    with pytest.raises(ValidationError):
        ComparisonRequest.model_validate({
            "instrument_code": "510300",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "templates": [{"id": "range_breakout", "version": "1.0.0"}],
        })
