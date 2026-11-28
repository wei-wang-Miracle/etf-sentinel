"""将 ETF 研究分类及 v1.5 研究结论支撑的通用/分类策略绑定关系落地数据库。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

CATEGORY_BY_CODE = {
    "159919": "大盘宽基",
    "510050": "大盘宽基",
    "510180": "大盘宽基",
    "510300": "大盘宽基",
    "510310": "大盘宽基",
    "510330": "大盘宽基",
    "159922": "中盘宽基",
    "510500": "中盘宽基",
    "512500": "中盘宽基",
    "159629": "小盘宽基",
    "159845": "小盘宽基",
    "512100": "小盘宽基",
    "560010": "小盘宽基",
    "159531": "微盘",
    "159205": "创业板",
    "159915": "创业板",
    "159952": "创业板",
    "159977": "创业板",
    "588050": "科创板",
    "588080": "科创板",
    "518880": "黄金",
    "515880": "通信设备",
    "560780": "半导体材料设备",
}

GEM_STRATEGY_FACTORS = [
    ("gem_bottom_contraction", "turning_bottom", "trigger", 0),
    ("gem_bottom_contraction", "volatility_contracting", "filter", 1),
    ("gem_bottom_contraction", "strong_close", "confirmation", 2),
    ("gem_bottom_contraction", "close_position_positive", "confirmation", 3),
    ("gem_bottom_contraction", "ma5_cross_ma20_down", "exit", 4),
    ("gem_bottom_contraction", "market_greed_extreme", "exit", 5),
]

STRATEGY_SCOPES = [
    {
        "strategy_id": "range_breakout",
        "category_name": "通用",
        "scope_type": "universal",
        "research_version": "shared-baseline-v1.0",
        "evidence_tier": "baseline",
        "adoptable": True,
        "evidence_summary": {
            "note": "现行共享箱体突破基准策略，支持全部配置内 ETF 比较与采用。"
        },
    },
    {
        "strategy_id": "bottom_confirmation",
        "category_name": "通用",
        "scope_type": "universal",
        "research_version": "shared-baseline-v1.0",
        "evidence_tier": "baseline",
        "adoptable": True,
        "evidence_summary": {
            "note": "现行共享底部确认基准策略，支持全部配置内 ETF 比较与采用。"
        },
    },
    {
        "strategy_id": "hybrid_reversal",
        "category_name": "通用",
        "scope_type": "universal",
        "research_version": "shared-baseline-v1.0",
        "evidence_tier": "baseline",
        "adoptable": True,
        "evidence_summary": {
            "note": "现行共享复合反转基准策略，支持全部配置内 ETF 比较与采用。"
        },
    },
    {
        "strategy_id": "trend_pullback",
        "category_name": "黄金",
        "scope_type": "category",
        "research_version": "factor-strategy-research-v1.5.0",
        "evidence_tier": "single_unit_candidate",
        "adoptable": True,
        "evidence_summary": {
            "development": {"completed": 11, "win_rate": 0.8182, "profit_factor": 4.17, "drawdown": -0.067},
            "holdout": {"completed": 5, "win_rate": 0.80, "profit_factor": 7.65, "drawdown": -0.049},
            "note": "v1.5.0 黄金分类达到单指数专精候选门槛，开发与留出普通/压力成本全部通过，开放采用。",
        },
    },
    {
        "strategy_id": "volatility_contraction_breakout",
        "category_name": "黄金",
        "scope_type": "category",
        "research_version": "factor-strategy-research-v1.5.0",
        "evidence_tier": "single_unit_candidate",
        "adoptable": True,
        "evidence_summary": {
            "development": {"completed": 22, "win_rate": 0.6364, "profit_factor": 4.17, "drawdown": -0.088},
            "holdout": {"completed": 10, "win_rate": 0.70, "profit_factor": 6.85, "drawdown": -0.029},
            "note": "v1.5.0 黄金分类达到单指数专精候选门槛，开发与留出普通/压力成本全部通过，开放采用。",
        },
    },
    {
        "strategy_id": "gem_bottom_contraction",
        "category_name": "创业板",
        "scope_type": "category",
        "research_version": "factor-strategy-research-v1.5.0",
        "evidence_tier": "holdout_watch",
        "adoptable": False,
        "evidence_summary": {
            "source_candidate": "c1329",
            "development": {"completed": 22, "win_rate": 0.8182, "profit_factor": 9.65, "drawdown": -0.078, "intra_positive": "3/3"},
            "holdout": {"completed": 7, "win_rate": 0.5714, "profit_factor": 2.97, "drawdown": -0.059, "intra_positive": "3/3"},
            "note": "v1.5.0 创业板领先候选 c1329 固化：类内3只全正且PF近3.0，因留出胜率57.1%略低于60%门槛暂观察。",
        },
    },
    {
        "strategy_id": "volatility_contraction_breakout",
        "category_name": "创业板",
        "scope_type": "category",
        "research_version": "factor-strategy-research-v1.5.0",
        "evidence_tier": "holdout_watch",
        "adoptable": False,
        "evidence_summary": {
            "development": {"completed": 51, "win_rate": 0.5490, "profit_factor": 2.56, "drawdown": -0.118},
            "holdout": {"completed": 13, "win_rate": 0.8462, "profit_factor": 26.96, "drawdown": -0.045},
            "note": "v1.5.0 创业板留出胜率84.6%/PF 26.96，但开发压力成本回撤略超-12%门槛，暂观察对比。",
        },
    },
    {
        "strategy_id": "value_sentiment_reversal",
        "category_name": "大盘宽基",
        "scope_type": "category",
        "research_version": "factor-strategy-research-v1.5.0",
        "evidence_tier": "rejected",
        "adoptable": False,
        "evidence_summary": {
            "development": {"completed": 160, "win_rate": 0.546, "profit_factor": 2.49, "drawdown": -0.167},
            "holdout": {"completed": 35, "win_rate": 0.507, "profit_factor": 1.38, "drawdown": -0.116},
            "note": "v1.5.0 大盘宽基开发期利润因子达2.49，但胜率与回撤未达门槛，保留大盘分类比较参照。",
        },
    },
    {
        "strategy_id": "value_sentiment_reversal",
        "category_name": "中盘宽基",
        "scope_type": "category",
        "research_version": "factor-strategy-research-v1.5.0",
        "evidence_tier": "rejected",
        "adoptable": False,
        "evidence_summary": {
            "development": {"completed": 97, "win_rate": 0.557, "profit_factor": 1.84, "drawdown": -0.210},
            "holdout": {"completed": 14, "win_rate": 0.286, "profit_factor": 0.54, "drawdown": -0.167},
            "note": "v1.5.0 中盘宽基开发期利润因子达1.84，留出走弱未过门槛，保留中盘分类比较参照。",
        },
    },
]


def upgrade():
    """添加标的分类字段、策略分类作用域表并写入 v1.5 研究结论绑定。"""
    op.add_column(
        "instruments",
        sa.Column(
            "research_category",
            sa.String(length=32),
            nullable=False,
            server_default="未分类",
            comment="研究资产分类（如大盘宽基、中盘宽基、小盘宽基、微盘、创业板、科创板、黄金、通信设备、半导体材料设备或未分类），用于策略分类展示与研究绑定",
        ),
    )
    for code, category in CATEGORY_BY_CODE.items():
        op.execute(
            sa.text(
                "UPDATE instruments SET research_category = :category WHERE instrument_code = :code"
            ).bindparams(category=category, code=code)
        )

    op.create_table(
        "research_strategy_scopes",
        sa.Column(
            "strategy_id",
            sa.String(length=64),
            primary_key=True,
            comment="代码目录中已冻结实现的策略稳定身份",
        ),
        sa.Column(
            "category_name",
            sa.String(length=32),
            primary_key=True,
            comment="绑定的研究资产分类名称；通用策略固定为通用",
        ),
        sa.Column(
            "scope_type",
            sa.String(length=16),
            nullable=False,
            comment="策略作用域枚举：universal表示通用策略，category表示分类专属策略",
        ),
        sa.Column(
            "research_version",
            sa.String(length=64),
            nullable=False,
            comment="支撑本条绑定或准入结论的离线研究版本号，如factor-strategy-research-v1.5.0",
        ),
        sa.Column(
            "evidence_tier",
            sa.String(length=32),
            nullable=False,
            comment="研究证据等级：cross_unit_verified跨独立指数验证、single_unit_candidate单指数专精候选、holdout_watch留出待观察、rejected未达标观察或baseline既有基准",
        ),
        sa.Column(
            "adoptable",
            sa.Boolean(),
            nullable=False,
            comment="研究结论是否已支持开放策略库采用并产生盘前信号；仅达门禁或既有基线策略为True",
        ),
        sa.Column(
            "evidence_summary",
            sa.JSON(),
            nullable=False,
            comment="研究实证摘要JSON：含development开发期与holdout留出期样本数/胜率/利润因子/最大回撤、类内一致率及结论说明",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="本条研究绑定结论写入或修订的本地时间，带时区",
        ),
        comment="研究结论支持的策略作用域（通用/分类）、分类绑定及采用准入状态；策略规则仍在代码定义",
    )

    relation_table = sa.table(
        "research_strategy_factors",
        sa.column("strategy_id", sa.String()),
        sa.column("factor_id", sa.String()),
        sa.column("role", sa.String()),
        sa.column("display_order", sa.Integer()),
    )
    relation_rows = [
        {
            "strategy_id": sid,
            "factor_id": fid,
            "role": role,
            "display_order": order,
        }
        for sid, fid, role, order in GEM_STRATEGY_FACTORS
    ]
    op.execute(
        insert(relation_table)
        .values(relation_rows)
        .on_conflict_do_nothing(index_elements=["strategy_id", "factor_id"])
    )

    scope_table = sa.table(
        "research_strategy_scopes",
        sa.column("strategy_id", sa.String()),
        sa.column("category_name", sa.String()),
        sa.column("scope_type", sa.String()),
        sa.column("research_version", sa.String()),
        sa.column("evidence_tier", sa.String()),
        sa.column("adoptable", sa.Boolean()),
        sa.column("evidence_summary", sa.JSON()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now_dt = datetime(2026, 11, 28, 13, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    op.execute(
        insert(scope_table)
        .values([{**row, "updated_at": now_dt} for row in STRATEGY_SCOPES])
        .on_conflict_do_nothing(index_elements=["strategy_id", "category_name"])
    )


def downgrade():
    """撤销策略分类作用域表、c1329 因子关系及标的分类字段。"""
    op.execute(
        sa.text(
            "DELETE FROM strategy_comparison_factors WHERE strategy_id = 'gem_bottom_contraction'"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM research_strategy_factors WHERE strategy_id = 'gem_bottom_contraction'"
        )
    )
    op.drop_table("research_strategy_scopes")
    op.drop_column("instruments", "research_category")
