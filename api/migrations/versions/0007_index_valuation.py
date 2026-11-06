"""新增关联指数估值、修订证据和独立日行情，保留既有数据。"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    """创建独立指数表并登记8指数、20关联和每日任务4。"""
    op.alter_column(
        "jobs",
        "job_id",
        comment="采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情",
    )
    op.alter_column(
        "runs",
        "job_id",
        comment="所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情",
    )
    op.create_table(
        "research_indices",
        sa.Column(
            "index_code",
            sa.String(),
            primary_key=True,
            nullable=False,
            comment="完整指数代码含市场后缀，保留前导零，如000905.SH",
        ),
        sa.Column(
            "index_name",
            sa.String(),
            primary_key=False,
            nullable=False,
            comment="指数中文名称，不与ETF名称混用",
        ),
        sa.Column(
            "chatbi_code",
            sa.String(length=6),
            primary_key=False,
            nullable=False,
            comment="ChatBI指数行情查询六位代码，保留前导零",
        ),
        sa.Column(
            "collection_enabled",
            sa.Boolean(),
            primary_key=False,
            nullable=False,
            comment="是否启用指数估值及日K采集；停用不删历史",
        ),
        comment="当前ETF关联研究指数，独立于ETF标的，按完整源代码去重",
    )
    op.create_table(
        "instrument_index_links",
        sa.Column(
            "instrument_code",
            sa.String(length=6),
            sa.ForeignKey("instruments.instrument_code"),
            primary_key=True,
            nullable=False,
            comment="ETF证券代码，关联instruments.instrument_code",
        ),
        sa.Column(
            "index_code",
            sa.String(),
            sa.ForeignKey("research_indices.index_code"),
            primary_key=True,
            nullable=False,
            comment="完整指数代码，关联research_indices.index_code",
        ),
        sa.Column(
            "mapping_evidence",
            sa.String(),
            primary_key=False,
            nullable=False,
            comment="映射核验依据，基金名称、国家队目录及源关联信息交叉核验，非仅凭相关性",
        ),
        sa.Column(
            "verified_date",
            sa.Date(),
            primary_key=False,
            nullable=False,
            comment="本系统映射核验北京时间日期，非指数数据日期",
        ),
        comment="当前ETF与研究指数关联；同一指数多只ETF共享一次采集",
    )
    op.create_table(
        "index_valuation_daily",
        sa.Column(
            "index_code",
            sa.String(),
            sa.ForeignKey("research_indices.index_code"),
            primary_key=True,
            nullable=False,
            comment="完整指数代码，关联research_indices.index_code",
        ),
        sa.Column(
            "metric_key",
            sa.String(),
            primary_key=True,
            nullable=False,
            comment="指标pe市盈率倍、pb市净率倍、xilv股息率百分数、roe净资产收益率百分数、premium_diff风险溢价差值百分点；源算法未确认",
        ),
        sa.Column(
            "trade_date",
            sa.Date(),
            primary_key=True,
            nullable=False,
            comment="源估值日期，非采集或发布日期；缺日不补造",
        ),
        sa.Column(
            "metric_value",
            sa.Numeric(precision=36, scale=18),
            primary_key=False,
            nullable=True,
            comment="源原始指标值，保留至18位小数；单位由metric_key定义，源缺失为空，无效值仍保留",
        ),
        sa.Column(
            "value_status",
            sa.String(),
            primary_key=False,
            nullable=False,
            comment="有效状态valid有效、missing源缺失、not_applicable非正PE/PB或负股息率；后两类不参与分位",
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            comment="本条首次入库或实际修订的本地时间，带时区；未变不重写",
        ),
        comment="指数五类日估值；保留源值，历史分位按本地公式另行计算；非原时点发布快照",
    )
    op.create_table(
        "index_valuation_revisions",
        sa.Column(
            "revision_id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
            comment="估值修订自增编号",
        ),
        sa.Column(
            "index_code",
            sa.String(),
            sa.ForeignKey("research_indices.index_code"),
            primary_key=False,
            nullable=False,
            comment="完整指数代码，关联research_indices.index_code",
        ),
        sa.Column(
            "metric_key",
            sa.String(),
            primary_key=False,
            nullable=False,
            comment="五类估值指标，与index_valuation_daily.metric_key同口径",
        ),
        sa.Column(
            "trade_date",
            sa.Date(),
            primary_key=False,
            nullable=False,
            comment="发生新增或修订的源估值日期",
        ),
        sa.Column(
            "old_value",
            sa.Numeric(precision=36, scale=18),
            primary_key=False,
            nullable=True,
            comment="修订前指标值，单位由metric_key定义；首次或原缺失为空",
        ),
        sa.Column(
            "new_value",
            sa.Numeric(precision=36, scale=18),
            primary_key=False,
            nullable=True,
            comment="本次指标值，单位由metric_key定义；源缺失为空",
        ),
        sa.Column(
            "old_status",
            sa.String(),
            primary_key=False,
            nullable=True,
            comment="修订前有效状态；首次观察为空",
        ),
        sa.Column(
            "new_status",
            sa.String(),
            primary_key=False,
            nullable=False,
            comment="本次有效状态valid、missing或not_applicable",
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            comment="本地实际观察到变更的带时区时间，非源发布时间",
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.run_id"),
            primary_key=False,
            nullable=False,
            comment="发生该观测的采集运行编号，关联runs.run_id",
        ),
        comment="估值输入修订证据；首次插入旧值及旧状态为空；与日估值同事务提交",
    )
    op.create_table(
        "index_valuation_snapshots",
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
            comment="来源快照自增编号",
        ),
        sa.Column(
            "index_code",
            sa.String(),
            sa.ForeignKey("research_indices.index_code"),
            primary_key=False,
            nullable=False,
            comment="完整指数代码，关联research_indices.index_code",
        ),
        sa.Column(
            "content_sha256",
            sa.String(length=64),
            primary_key=False,
            nullable=False,
            comment="规范JSON内容SHA256摘要，用于相邻观测去重",
        ),
        sa.Column(
            "source_payload",
            sa.JSON(),
            primary_key=False,
            nullable=False,
            comment="源JSON对象：overview概览含ROE原小数、detail详情、history各指标整段元统计和实际覆盖；无鉴权信息",
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            comment="本地读取该快照时间，带时区；非源发布日期",
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("runs.run_id"),
            primary_key=False,
            nullable=False,
            comment="本次观测采集运行编号，关联runs.run_id",
        ),
        comment="估值来源摘要观测快照，不包含推荐文案展示；按相邻内容变化归档，非历史发布版本",
    )
    op.create_table(
        "index_candles",
        sa.Column(
            "index_code",
            sa.String(),
            sa.ForeignKey("research_indices.index_code"),
            primary_key=True,
            nullable=False,
            comment="完整指数代码，关联research_indices.index_code",
        ),
        sa.Column(
            "trade_date",
            sa.Date(),
            primary_key=True,
            nullable=False,
            comment="行情源交易日期，非采集时间",
        ),
        sa.Column(
            "open_price",
            sa.Numeric(precision=24, scale=8),
            primary_key=False,
            nullable=False,
            comment="日开盘指数点位，源口径",
        ),
        sa.Column(
            "high_price",
            sa.Numeric(precision=24, scale=8),
            primary_key=False,
            nullable=False,
            comment="日最高指数点位，源口径",
        ),
        sa.Column(
            "low_price",
            sa.Numeric(precision=24, scale=8),
            primary_key=False,
            nullable=False,
            comment="日最低指数点位，源口径",
        ),
        sa.Column(
            "close_price",
            sa.Numeric(precision=24, scale=8),
            primary_key=False,
            nullable=False,
            comment="日收盘指数点位，源口径",
        ),
        sa.Column(
            "trading_volume",
            sa.Numeric(precision=30, scale=4),
            primary_key=False,
            nullable=False,
            comment="日成交量源数值，单位未确认",
        ),
        sa.Column(
            "trading_amount",
            sa.Numeric(precision=30, scale=4),
            primary_key=False,
            nullable=False,
            comment="日成交额源数值，单位未确认",
        ),
        sa.Column(
            "price_change_pct",
            sa.Numeric(precision=20, scale=8),
            primary_key=False,
            nullable=True,
            comment="相对昨收涨跌幅百分数，如1为1%；源缺失为空",
        ),
        sa.Column(
            "source_updated_at",
            sa.String(),
            primary_key=False,
            nullable=True,
            comment="行情源更新时间原始文本，源时区未确认；可空",
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            comment="本条首次入库或实际源修订的带时区采集时间",
        ),
        comment="ChatBI daily_ohlcv_index指数原始日行情；价格字段为指数点位，非ETF价格",
    )
    op.create_table(
        "index_collection_windows",
        sa.Column(
            "index_code",
            sa.String(),
            sa.ForeignKey("research_indices.index_code"),
            primary_key=True,
            nullable=False,
            comment="完整指数代码，关联research_indices.index_code",
        ),
        sa.Column(
            "collection_start_date",
            sa.Date(),
            primary_key=True,
            nullable=False,
            comment="成功查询窗口起始日期，含当日",
        ),
        sa.Column(
            "collection_end_date",
            sa.Date(),
            primary_key=False,
            nullable=False,
            comment="成功查询窗口截止日期，含当日；失败不推进",
        ),
        comment="指数日K成功查询区间水位；空响应也记录，不代表交易日完整性已验证",
    )
    op.execute(
        "INSERT INTO research_indices VALUES ('000300.SH', '沪深300', '000300', true)"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('510300', '000300.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('510310', '000300.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('510330', '000300.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('159919', '000300.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO research_indices VALUES ('000016.SH', '上证50', '000016', true)"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('510050', '000016.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO research_indices VALUES ('000010.SH', '上证180', '000010', true)"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('510180', '000010.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO research_indices VALUES ('000905.SH', '中证500', '000905', true)"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('510500', '000905.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('512500', '000905.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('159922', '000905.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO research_indices VALUES ('000852.SH', '中证1000', '000852', true)"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('512100', '000852.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('159845', '000852.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('560010', '000852.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('159629', '000852.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO research_indices VALUES ('399006.SZ', '创业板指', '399006', true)"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('159915', '399006.SZ', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('159952', '399006.SZ', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('159977', '399006.SZ', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('159205', '399006.SZ', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO research_indices VALUES ('000688.SH', '科创50', '000688', true)"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('588080', '000688.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('588050', '000688.SH', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO research_indices VALUES ('932000.CSI', '中证2000', '932000', true)"
    )
    op.execute(
        "INSERT INTO instrument_index_links VALUES ('159531', '932000.CSI', '基金名称、国家队目录及源基金关联信息交叉核验', '2026-11-06')"
    )
    op.execute(
        "INSERT INTO jobs (job_id, schedule_enabled, scheduled_time) VALUES (4, true, '01:30')"
    )


def downgrade():
    """删除本次指数数据及任务4，不影响ETF和其他采集任务。"""
    op.alter_column(
        "jobs",
        "job_id",
        comment="采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例",
    )
    op.alter_column(
        "runs",
        "job_id",
        comment="所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例",
    )
    op.drop_table("index_collection_windows")
    op.drop_table("index_candles")
    op.drop_table("index_valuation_snapshots")
    op.drop_table("index_valuation_revisions")
    op.drop_table("index_valuation_daily")
    op.drop_table("instrument_index_links")
    op.drop_table("research_indices")
    op.execute("DELETE FROM runs WHERE job_id = 4")
    op.execute("DELETE FROM jobs WHERE job_id = 4")
