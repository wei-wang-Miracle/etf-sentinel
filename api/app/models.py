"""行情、配置及可恢复采集进度的持久化模型。"""

from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """业务模型基类。"""


class Instrument(Base):
    """统一研究标的及历史回补边界。"""

    __tablename__ = "instruments"
    __table_args__: ClassVar[dict] = {
        "comment": "ETF研究标的及采集配置；停用不删除已入库行情"
    }
    code: Mapped[str] = mapped_column(
        "instrument_code",
        String(6),
        primary_key=True,
        comment="ETF证券代码，六位字符串，保留前导零；统一行情研究标的",
    )
    name: Mapped[str] = mapped_column(
        "instrument_name",
        default="名称待采集",
        comment="ETF名称，行情源返回后更新；国家队新增标的初始名称来自国家队目录",
    )
    enabled: Mapped[bool] = mapped_column(
        "collection_enabled",
        default=True,
        comment="是否启用后续行情采集；不影响历史行情查询",
    )
    start_date: Mapped[Date] = mapped_column(
        "collection_start_date",
        default=Date(2020, 1, 1),
        comment="历史采集起始日期，含当日；调早回补，调晚不删除历史",
    )


class Candle(Base):
    """源口径日行情，代码与交易日共同唯一。"""

    __tablename__ = "candles"
    __table_args__: ClassVar[dict] = {
        "comment": "ETF历史日行情；按证券代码和交易日期唯一，源修订幂等覆盖"
    }
    code: Mapped[str] = mapped_column(
        "instrument_code",
        ForeignKey("instruments.instrument_code"),
        primary_key=True,
        comment="ETF证券代码，关联instruments.instrument_code",
    )
    date: Mapped[Date] = mapped_column(
        "trade_date", primary_key=True, comment="数据源交易日期，非采集日期；按源值保存"
    )
    open: Mapped[Decimal] = mapped_column(
        "open_price", Numeric(24, 8), comment="原始日开盘价，人民币元；未推断复权口径"
    )
    high: Mapped[Decimal] = mapped_column(
        "high_price", Numeric(24, 8), comment="原始日最高价，人民币元；未推断复权口径"
    )
    low: Mapped[Decimal] = mapped_column(
        "low_price", Numeric(24, 8), comment="原始日最低价，人民币元；未推断复权口径"
    )
    close: Mapped[Decimal] = mapped_column(
        "close_price", Numeric(24, 8), comment="原始日收盘价，人民币元；未推断复权口径"
    )
    volume: Mapped[Decimal] = mapped_column(
        "trading_volume",
        Numeric(30, 4),
        comment="日成交量，保留源数值；单位待数据源确认",
    )
    amount: Mapped[Decimal] = mapped_column(
        "trading_amount",
        Numeric(30, 4),
        comment="日成交额，保留源数值；单位待数据源确认",
    )
    change_pct: Mapped[Decimal | None] = mapped_column(
        "price_change_pct",
        Numeric(20, 8),
        comment="相对昨收涨跌幅，百分数单位，如1表示1%",
    )
    adjusted_close: Mapped[Decimal | None] = mapped_column(
        "adjusted_close_price",
        Numeric(24, 8),
        comment="源ADJUSTED_CLOSE复权收盘值；前后复权类型尚未确认；可空",
    )
    source_updated_at: Mapped[str | None] = mapped_column(
        "source_updated_at", comment="数据源更新时间原始文本；源时区未确认；可空"
    )
    collected_at: Mapped[datetime] = mapped_column(
        "collected_at",
        DateTime(timezone=True),
        comment="本系统成功采集时间，带时区时间戳",
    )


class Job(Base):
    """按业务独立配置的每日采集任务。"""

    __tablename__ = "jobs"
    __table_args__: ClassVar[dict] = {"comment": "采集任务配置；执行时区Asia/Shanghai"}
    id: Mapped[int] = mapped_column(
        "job_id",
        primary_key=True,
        comment="采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划，6为全市场恐贪与五维环境因子，7为ETF档案与份额流",
    )
    enabled: Mapped[bool] = mapped_column(
        "schedule_enabled", default=True, comment="是否启用每日调度；不禁止手动触发"
    )
    time: Mapped[str] = mapped_column(
        "scheduled_time",
        default="01:00",
        comment="每日北京时间执行时刻，24小时HH:mm格式",
    )
    last_scheduled_date: Mapped[Date | None] = mapped_column(
        "last_scheduled_date",
        comment="最近一次成功触发定时运行的北京时间日期；非采集完成日；可空",
    )


class Run(Base):
    """采集运行状态与不含凭据的区间日志。"""

    __tablename__ = "runs"
    __table_args__: ClassVar[dict] = {
        "comment": "采集任务运行记录；保留运行状态及不含凭据的区间日志"
    }
    id: Mapped[int] = mapped_column(
        "run_id", primary_key=True, comment="单次采集运行唯一编号，自增主键"
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.job_id"),
        default=1,
        comment="所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划，6为全市场恐贪与五维环境因子，7为ETF档案与份额流",
    )
    status: Mapped[str] = mapped_column(
        "run_status",
        default="running",
        comment="运行状态：running运行中、success成功、partial部分失败、failed失败、interrupted中断",
    )
    trigger: Mapped[str] = mapped_column(
        "trigger_type", comment="触发方式：manual手动、scheduled定时"
    )
    started_at: Mapped[datetime] = mapped_column(
        "started_at", DateTime(timezone=True), comment="运行开始时间，带时区时间戳"
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        "ended_at",
        DateTime(timezone=True),
        comment="运行结束或中断时间，带时区时间戳；运行中为空",
    )
    logs: Mapped[list] = mapped_column(
        "collection_logs",
        JSON,
        default=list,
        comment="区间日志JSON数组；元素含code标的、start/end请求闭区间、status、count返回条数、message安全摘要；不保存凭据",
    )


class Window(Base):
    """已成功查询的区间，空响应也保存；失败区间不推进。"""

    __tablename__ = "collection_windows"
    __table_args__: ClassVar[dict] = {
        "comment": "已成功查询的历史区间；空响应也记录，复查失败撤销进度以便重试"
    }
    code: Mapped[str] = mapped_column(
        "instrument_code",
        ForeignKey("instruments.instrument_code"),
        primary_key=True,
        comment="ETF证券代码，关联instruments.instrument_code",
    )
    start: Mapped[Date] = mapped_column(
        "collection_start_date",
        primary_key=True,
        comment="成功查询区间起始日期，含当日；与instrument_code组成主键",
    )
    end: Mapped[Date] = mapped_column(
        "collection_end_date",
        comment="成功查询区间截止日期，含当日；不代表区间交易日完整性已验证",
    )


class SentimentCategory(Base):
    """恐贪类别目录及源最新快照，不推断历史情绪标签。"""

    __tablename__ = "sentiment_categories"
    __table_args__: ClassVar[dict] = {
        "comment": "韭圈行业恐贪类别目录及源快照；包括行业、固收与美股，不与ETF自动关联"
    }
    category_key: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="源类别唯一标识，如gf军工、qs券商；主外键统一使用category_key",
    )
    category_name: Mapped[str] = mapped_column(
        comment="数据源类别显示名称，不根据key自行推断"
    )
    index_name: Mapped[str | None] = mapped_column(
        comment="历史序列返回的关联指数名称；尚未返回时为空"
    )
    collection_enabled: Mapped[bool] = mapped_column(
        default=True, comment="是否采集该类别，停用不删除历史；新发现类别默认启用"
    )
    snapshot_date: Mapped[Date | None] = mapped_column(
        comment="源目录最新快照日期；保持源日期，不推断时区；可空"
    )
    snapshot_score: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4), comment="源最新快照恐贪分数0至100；0有效；缺失为空"
    )
    snapshot_label: Mapped[str | None] = mapped_column(
        comment="源最新快照情绪标签；仅日期与分数匹配本地日数据时展示；可空"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="本系统最近成功读取类别目录时间，带时区时间戳"
    )


class SentimentDaily(Base):
    """按类别和源日期唯一保存的恐贪历史日数据。"""

    __tablename__ = "sentiment_daily"
    __table_args__: ClassVar[dict] = {
        "comment": "行业恐贪历史日序列，含关联指数收盘；原始源日期保存，零分有效，不自行计算情绪阈值"
    }
    category_key: Mapped[str] = mapped_column(
        ForeignKey("sentiment_categories.category_key"),
        primary_key=True,
        comment="源类别唯一标识，关联sentiment_categories.category_key",
    )
    trade_date: Mapped[Date] = mapped_column(
        primary_key=True, comment="数据源序列日期，非采集日期；不统一截为北京时间昨日"
    )
    fear_greed_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), comment="恐贪分数，闭区间0至100，0为有效值；计算公式由源提供"
    )
    close_price: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8), comment="关联指数收盘点位，非ETF价格；源缺失时为空"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="本系统本条日数据最近采集时间，带时区时间戳"
    )


class MarketFearGreedDaily(Base):
    """全市场恐贪总分的源日频观测。"""

    __tablename__ = "market_fear_greed_daily"
    __table_args__: ClassVar[dict] = {
        "comment": "全市场恐贪指数源日频序列；零分有效，不从当前快照推断历史情绪标签"
    }
    trade_date: Mapped[Date] = mapped_column(
        primary_key=True,
        comment="数据源交易日期，按源值保存，不统一截为北京时间昨日",
    )
    fear_greed_score: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        comment="全市场恐贪总分，闭区间0至100，零为有效值",
    )
    source_label: Mapped[str | None] = mapped_column(
        String(32),
        comment="源最新快照情绪标签；仅源日期与总分完全匹配时写入，其余历史日期为空",
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        comment="本条首次入库或源值实际修订的本地采集时间，带时区；未变化不重写",
    )


class MarketRegimeFactorDaily(Base):
    """全市场五维环境子因子的源日频观测。"""

    __tablename__ = "market_regime_factor_daily"
    __table_args__ = (
        Index("ix_market_regime_factor_daily_trade_date", "trade_date"),
        {
            "comment": "全市场恐贪五维环境子因子源日频序列；源分位仅供展示，不作为历史策略分位"
        },
    )
    factor_key: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        comment="源子因子标识：volatility、bx、premium、wz、strength；与trade_date组成主键",
    )
    trade_date: Mapped[Date] = mapped_column(
        primary_key=True,
        comment="数据源交易日期，按源值保存；与factor_key组成主键",
    )
    factor_name: Mapped[str] = mapped_column(
        String(100), comment="源中文名称，不自行重命名或猜测指标含义"
    )
    raw_value: Mapped[Decimal] = mapped_column(
        Numeric(24, 6),
        comment="源原始读数，允许正负数；具体单位随factor_key和源口径保留，不擅自换算",
    )
    source_pct_year: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        comment="源返回的近一年分位，范围0至100；仅供观察对照，不作为历史固定时点分位；可空",
    )
    source_pct_all: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 4),
        comment="源返回的全历史分位，范围0至100；仅供观察对照，不作为历史固定时点分位；可空",
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        comment="本条首次入库或字段实际修订的本地采集时间，带时区；未变化不重写",
    )


class NationalTeamInstrument(Base):
    """独立的国家队源目录，不扩写已有行情采集标的。"""

    __tablename__ = "national_team_instruments"
    __table_args__: ClassVar[dict] = {
        "comment": "国家队ETF源目录及固定估算基准；比例为第三方推算，不代表实际持仓"
    }
    instrument_code: Mapped[str] = mapped_column(
        String(6), primary_key=True, comment="源ETF证券代码，六位字符串，保留前导零"
    )
    instrument_name: Mapped[str] = mapped_column(comment="源ETF名称，不使用行情近似价格")
    index_name: Mapped[str] = mapped_column(comment="源ETF跟踪指数名称，非指数代码")
    estimation_start_date: Mapped[Date] = mapped_column(
        comment="固定请求与估算起点2026-01-01；筛选日期和跨年不重置，不同起点比例不可拼接"
    )
    reference_holding_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8), comment="源hold_pct年报基准持仓比例，百分数0至100；上游披露未核实；可空"
    )
    source_url: Mapped[str] = mapped_column(comment="固定第三方源接口地址，不包含凭据")
    source_available: Mapped[bool] = mapped_column(
        default=True, comment="最近成功读取的源目录是否包含该ETF；缺失不删除历史"
    )
    last_success_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="该ETF最近完整核验并成功增量入库时间，带时区；不代表源行情日期"
    )


class NationalTeamDaily(Base):
    """仅存固定基准下的估算比例，不重复存价格或总份额。"""

    __tablename__ = "national_team_daily"
    __table_args__: ClassVar[dict] = {
        "comment": "国家队ETF源日估算比例；同代码同源日期唯一；不作为真实持仓或交易信号"
    }
    instrument_code: Mapped[str] = mapped_column(
        ForeignKey("national_team_instruments.instrument_code"), primary_key=True,
        comment="源ETF证券代码，关联national_team_instruments.instrument_code"
    )
    trade_date: Mapped[Date] = mapped_column(
        primary_key=True, comment="源points.date交易日期，保留源日历日期，不使用请求截止日"
    )
    estimated_holding_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8), comment="源nat_pct估算持仓比例，百分数0至100；有效份额下零有效；份额为零或源比例缺失时为空"
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="本条首次入库或源比例实际修订的采集时间，带时区；未变化不重写"
    )


class BacktestSource(Base):
    """回测权益来源快照，包含完整分红与折算事件及原始页面证据。"""

    __tablename__ = "backtest_sources"
    __table_args__: ClassVar[dict] = {"comment": "配置内ETF回测现金分红与折算来源；按权益、日历和行情动态核验资格，不作为行情价格"}
    instrument_code: Mapped[str] = mapped_column(
        ForeignKey("instruments.instrument_code"), primary_key=True,
        comment="证券代码，关联instruments.instrument_code；仅限配置内ETF",
    )
    source_url: Mapped[str] = mapped_column(comment="东方财富基金分红送配页面URL，不包含凭据")
    checked_through_date: Mapped[Date] = mapped_column(comment="本次读取权益页面的北京时间日期；表示读取时点，不保证来源绝对完整")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="本系统读取并校验权益页面时间，带时区")
    source_sha256: Mapped[str] = mapped_column(String(64), comment="源页面字节的SHA256摘要，用于核对原始证据")
    source_html: Mapped[str] = mapped_column(comment="已获取权益源页面原始HTML，仅作证据，不在前端渲染")
    corporate_actions: Mapped[dict] = mapped_column(JSON, comment="权益JSON：dividends数组含record_date登记日、ex_date除息日、pay_date到账日、cash_per_share每份人民币元字符串；splits数组含effective_date折算日及ratio源比例")


class BacktestRun(Base):
    """不可变回测实验，保存输入与完整结果以脱离后续行情修订复现。"""

    __tablename__ = "backtest_runs"
    __table_args__: ClassVar[dict] = {"comment": "已成功完成的策略回测实验；仅研究模拟，非交易记录；输入与结果不可变"}
    backtest_run_id: Mapped[int] = mapped_column(primary_key=True, comment="回测实验唯一自增编号，与采集运行编号无关")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), comment="回测证券代码，关联instruments.instrument_code")
    strategy_key: Mapped[str] = mapped_column(comment="策略注册标识，ma_trend为均线趋势；规则版本位于输入快照")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="回测完成并写入本地时间，带时区")
    input_sha256: Mapped[str] = mapped_column(String(64), comment="含参数、预热行情、权益、来源和版本的规范JSON SHA256摘要")
    input_snapshot: Mapped[dict] = mapped_column(JSON, comment="不可变输入JSON：settings参数、rows原始行情与采集时间、actions权益、来源快照、交易日历及策略/引擎/数据版本；金额使用十进制字符串")
    result_snapshot: Mapped[dict] = mapped_column(JSON, comment="结果JSON：strategy与benchmark含daily逐日现金/份额/分红应收/净值/回撤/决策、trades成交及费用原因、dividends权益账本、metrics绩效；金额十进制字符串，收益率小数")


class ResearchIndex(Base):
    """与当前ETF明确关联的独立指数目录。"""

    __tablename__ = "research_indices"
    __table_args__: ClassVar[dict] = {"comment": "当前ETF关联研究指数，独立于ETF标的，按完整源代码去重"}
    index_code: Mapped[str] = mapped_column(primary_key=True, comment="完整指数代码含市场后缀，保留前导零，如000905.SH")
    index_name: Mapped[str] = mapped_column(comment="指数中文名称，不与ETF名称混用")
    chatbi_code: Mapped[str] = mapped_column(String(6), comment="ChatBI指数行情查询六位代码，保留前导零")
    collection_enabled: Mapped[bool] = mapped_column(default=True, comment="是否启用指数估值及日K采集；停用不删历史")


class InstrumentIndexLink(Base):
    """ETF与其跟踪指数的核验关联。"""

    __tablename__ = "instrument_index_links"
    __table_args__: ClassVar[dict] = {"comment": "当前ETF与研究指数关联；同一指数多只ETF共享一次采集"}
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), primary_key=True, comment="ETF证券代码，关联instruments.instrument_code")
    index_code: Mapped[str] = mapped_column(ForeignKey("research_indices.index_code"), primary_key=True, comment="完整指数代码，关联research_indices.index_code")
    mapping_evidence: Mapped[str] = mapped_column(comment="映射核验依据，基金名称、国家队目录及源关联信息交叉核验，非仅凭相关性")
    verified_date: Mapped[Date] = mapped_column(comment="本系统映射核验北京时间日期，非指数数据日期")


class InstrumentSentimentLink(Base):
    """ETF 与行业恐贪类别的显式核验关联。"""

    __tablename__ = "instrument_sentiment_links"
    __table_args__ = (
        Index("ix_instrument_sentiment_links_category_key", "category_key"),
        {
            "comment": "ETF与行业恐贪类别的显式核验关联；未建立关联的ETF不得使用行业恐贪因子"
        },
    )
    instrument_code: Mapped[str] = mapped_column(
        ForeignKey("instruments.instrument_code"),
        primary_key=True,
        comment="ETF证券代码，关联instruments.instrument_code；与category_key组成主键",
    )
    category_key: Mapped[str] = mapped_column(
        ForeignKey("sentiment_categories.category_key"),
        primary_key=True,
        comment="行业恐贪类别标识，关联sentiment_categories.category_key；与instrument_code组成主键",
    )
    mapping_evidence: Mapped[str] = mapped_column(
        Text,
        comment="ETF与恐贪类别的核验依据，不根据名称或相关性自动推断"
    )
    verified_date: Mapped[Date] = mapped_column(
        comment="本系统确认该ETF与恐贪类别关联的北京时间日期，非情绪数据日期"
    )


class IndexValuationDaily(Base):
    """指数日频估值当前版本，源历史无逐日分位。"""

    __tablename__ = "index_valuation_daily"
    __table_args__: ClassVar[dict] = {"comment": "指数五类日估值；保留源值，历史分位按本地公式另行计算；非原时点发布快照"}
    index_code: Mapped[str] = mapped_column(ForeignKey("research_indices.index_code"), primary_key=True, comment="完整指数代码，关联research_indices.index_code")
    metric_key: Mapped[str] = mapped_column(primary_key=True, comment="指标pe市盈率倍、pb市净率倍、xilv股息率百分数、roe净资产收益率百分数、premium_diff风险溢价差值百分点；源算法未确认")
    trade_date: Mapped[Date] = mapped_column(primary_key=True, comment="源估值日期，非采集或发布日期；缺日不补造")
    metric_value: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), comment="源原始指标值，保留至18位小数；单位由metric_key定义，源缺失为空，无效值仍保留")
    value_status: Mapped[str] = mapped_column(comment="有效状态valid有效、missing源缺失、not_applicable非正PE/PB或负股息率；后两类不参与分位")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="本条首次入库或实际修订的本地时间，带时区；未变不重写")


class IndexValuationRevision(Base):
    """估值值及有效状态的每次观测变更证据。"""

    __tablename__ = "index_valuation_revisions"
    __table_args__: ClassVar[dict] = {"comment": "估值输入修订证据；首次插入旧值及旧状态为空；与日估值同事务提交"}
    revision_id: Mapped[int] = mapped_column(primary_key=True, comment="估值修订自增编号")
    index_code: Mapped[str] = mapped_column(ForeignKey("research_indices.index_code"), comment="完整指数代码，关联research_indices.index_code")
    metric_key: Mapped[str] = mapped_column(comment="五类估值指标，与index_valuation_daily.metric_key同口径")
    trade_date: Mapped[Date] = mapped_column(comment="发生新增或修订的源估值日期")
    old_value: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), comment="修订前指标值，单位由metric_key定义；首次或原缺失为空")
    new_value: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), comment="本次指标值，单位由metric_key定义；源缺失为空")
    old_status: Mapped[str | None] = mapped_column(comment="修订前有效状态；首次观察为空")
    new_status: Mapped[str] = mapped_column(comment="本次有效状态valid、missing或not_applicable")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="本地实际观察到变更的带时区时间，非源发布时间")
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.run_id"), comment="发生该观测的采集运行编号，关联runs.run_id")


class IndexValuationSnapshot(Base):
    """概览、详情与历史整段统计按内容变化归档。"""

    __tablename__ = "index_valuation_snapshots"
    __table_args__: ClassVar[dict] = {"comment": "估值来源摘要观测快照，不包含推荐文案展示；按相邻内容变化归档，非历史发布版本"}
    snapshot_id: Mapped[int] = mapped_column(primary_key=True, comment="来源快照自增编号")
    index_code: Mapped[str] = mapped_column(ForeignKey("research_indices.index_code"), comment="完整指数代码，关联research_indices.index_code")
    content_sha256: Mapped[str] = mapped_column(String(64), comment="规范JSON内容SHA256摘要，用于相邻观测去重")
    source_payload: Mapped[dict] = mapped_column(JSON, comment="源JSON对象：overview概览含ROE原小数、detail详情、history各指标整段元统计和实际覆盖；无鉴权信息")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="本地读取该快照时间，带时区；非源发布日期")
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.run_id"), comment="本次观测采集运行编号，关联runs.run_id")


class IndexCandle(Base):
    """指数OHLC点位，与ETF人民币价格分开保存。"""

    __tablename__ = "index_candles"
    __table_args__: ClassVar[dict] = {"comment": "ChatBI daily_ohlcv_index指数原始日行情；价格字段为指数点位，非ETF价格"}
    index_code: Mapped[str] = mapped_column(ForeignKey("research_indices.index_code"), primary_key=True, comment="完整指数代码，关联research_indices.index_code")
    trade_date: Mapped[Date] = mapped_column(primary_key=True, comment="行情源交易日期，非采集时间")
    open_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), comment="日开盘指数点位，源口径")
    high_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), comment="日最高指数点位，源口径")
    low_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), comment="日最低指数点位，源口径")
    close_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), comment="日收盘指数点位，源口径")
    trading_volume: Mapped[Decimal] = mapped_column(Numeric(30, 4), comment="日成交量源数值，单位未确认")
    trading_amount: Mapped[Decimal] = mapped_column(Numeric(30, 4), comment="日成交额源数值，单位未确认")
    price_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), comment="相对昨收涨跌幅百分数，如1为1%；源缺失为空")
    source_updated_at: Mapped[str | None] = mapped_column(comment="行情源更新时间原始文本，源时区未确认；可空")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="本条首次入库或实际源修订的带时区采集时间")


class IndexCollectionWindow(Base):
    """按指数保存成功查询窗口，复查失败撤销以便重试。"""

    __tablename__ = "index_collection_windows"
    __table_args__: ClassVar[dict] = {"comment": "指数日K成功查询区间水位；空响应也记录，不代表交易日完整性已验证"}
    index_code: Mapped[str] = mapped_column(ForeignKey("research_indices.index_code"), primary_key=True, comment="完整指数代码，关联research_indices.index_code")
    collection_start_date: Mapped[Date] = mapped_column(primary_key=True, comment="成功查询窗口起始日期，含当日")
    collection_end_date: Mapped[Date] = mapped_column(comment="成功查询窗口截止日期，含当日；失败不推进")


class Account(Base):
    """本地真实账户；资金号只从环境变量读取，不落库。"""

    __tablename__ = "accounts"
    __table_args__: ClassVar[dict] = {"comment": "本地真实账户标识；不保存资金账号、股东账号或券商凭据"}
    account_id: Mapped[int] = mapped_column(primary_key=True, comment="本系统账户编号，与券商资金号无关")
    account_name: Mapped[str] = mapped_column(default="默认账户", comment="本地显示名称，例如默认账户")
    base_currency: Mapped[str] = mapped_column(String(3), default="CNY", comment="账户本位币，ISO三位代码；本期仅人民币CNY")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="账户在本系统建立时间，带时区")


class AccountSyncRun(Base):
    """账户持仓与成交同步批次。"""

    __tablename__ = "account_sync_runs"
    __table_args__: ClassVar[dict] = {"comment": "配置内账户数据同步批次；记录抓取、入库、跳过和错误数量，不保存敏感明细"}
    sync_run_id: Mapped[int] = mapped_column(primary_key=True, comment="同步批次自增编号")
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.account_id"), comment="本地账户编号，关联accounts.account_id")
    status: Mapped[str] = mapped_column(String(12), comment="同步状态running运行中、success成功、partial部分行错误、failed失败")
    range_start: Mapped[Date | None] = mapped_column(comment="本次抓取的委托起始日期，含当日；首次同步前为空")
    range_end: Mapped[Date | None] = mapped_column(comment="本次抓取的委托截止日期，含当日；首次同步前为空")
    holdings_snapshot: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), comment="完整持仓集合JSON：instrument_codes代码数组、source_date源日期或空、collected_at带时区采集时间；空数组表示真实空集合；NULL为旧版本或本次未取得完整快照，不将其当作空仓")
    fetched_count: Mapped[int] = mapped_column(default=0, comment="本次源返回的持仓与委托总行数")
    stored_count: Mapped[int] = mapped_column(default=0, comment="本次按配置内过滤后写入或更新的行数")
    skipped_count: Mapped[int] = mapped_column(default=0, comment="本次因不在配置内而跳过的行数；不保存明细")
    error_count: Mapped[int] = mapped_column(default=0, comment="配置内字段非法而未入库的行数")
    error_message: Mapped[str | None] = mapped_column(comment="错误摘要，最多保留前几条；不含资金号或设备信息")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="同步开始时间，带时区")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="同步结束时间，带时区；运行中为空")


class AccountHoldingSnapshot(Base):
    """配置内 ETF 当前持仓快照。"""

    __tablename__ = "account_holdings_snapshots"
    __table_args__: ClassVar[dict] = {"comment": "配置内ETF真实持仓快照；按账户、源数据日期和代码唯一；只存当前源快照"}
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.account_id"), primary_key=True, comment="本地账户编号，关联accounts.account_id")
    data_date: Mapped[Date] = mapped_column(primary_key=True, comment="源持仓数据日期，非本地采集日期")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), primary_key=True, comment="ETF证券代码，关联instruments.instrument_code；只存配置内标的")
    current_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, comment="当前持仓数量，份")
    enable_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, comment="可用数量，份；T+1下当日买入不可卖")
    frozen_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, comment="冻结数量，份")
    uncome_buy_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, comment="在途买入数量，份")
    uncome_sell_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, comment="在途卖出数量，份")
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), comment="源成本价，人民币元/份；源口径未披露费用处理，可空")
    sum_buy_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), comment="源当前持仓周期累计买入数量，份；可空")
    sum_buy_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), comment="源当前持仓周期累计买入金额，人民币元；可空")
    sum_sell_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), comment="源当前持仓周期累计卖出数量，份；可空")
    sum_sell_balance: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), comment="源当前持仓周期累计卖出金额，人民币元；可空")
    source_etl_time: Mapped[str | None] = mapped_column(comment="源更新时间原始文本，时区未确认；可空")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="本系统实际采集时间，带时区")


class AccountEntrust(Base):
    """配置内 ETF 委托及成交记录。"""

    __tablename__ = "account_entrusts"
    __table_args__: ClassVar[dict] = {
        "comment": "配置内ETF真实委托与成交；按账户、委托日期和委托编号唯一；保留原始状态和推导费用",
    }
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.account_id"), primary_key=True, comment="本地账户编号，关联accounts.account_id")
    curr_date: Mapped[Date] = mapped_column(primary_key=True, comment="源委托日期，非本地采集日期")
    entrust_no: Mapped[str] = mapped_column(String(32), primary_key=True, comment="源委托编号；不保证全局唯一，与委托日期组成唯一键")
    curr_time: Mapped[str | None] = mapped_column(String(16), comment="源委托时间原始文本，9位HHMMSSmmm；可空")
    init_date: Mapped[Date | None] = mapped_column(comment="源委托发起日期；可空")
    order_id: Mapped[str | None] = mapped_column(String(32), comment="源订单编号原始文本；可空")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), comment="ETF证券代码，关联instruments.instrument_code；只存配置内标的")
    entrust_side: Mapped[str] = mapped_column(String(1), comment="委托方向源值1买入、2卖出；未确认其他值按原值保存")
    entrust_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, comment="委托数量，份")
    entrust_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0, comment="委托价格，人民币元/份")
    entrust_type: Mapped[str | None] = mapped_column(String(8), comment="源委托类型原始值；可空")
    business_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, comment="成交数量，份；零表示未成交")
    business_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0, comment="成交价格，人民币元/份")
    business_balance: Mapped[Decimal] = mapped_column(Numeric(24, 4), default=0, comment="源成交金额，人民币元；未确认是否含费用")
    clear_balance: Mapped[Decimal] = mapped_column(Numeric(24, 4), default=0, comment="源清算金额，人民币元；与成交金额差额用于推导费用")
    withdraw_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0, comment="撤单数量，份；零表示未撤单")
    entrust_status: Mapped[str | None] = mapped_column(String(8), comment="源委托状态原始值；含义未确认，不硬编码中文翻译")
    fare_kind: Mapped[str | None] = mapped_column(String(16), comment="源费用类别原始值；可空")
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, comment="由成交金额与清算金额差额推导的费用，人民币元；非券商逐笔明细")
    data_date: Mapped[Date] = mapped_column(comment="源数据日期，非本地采集日期")
    source_etl_time: Mapped[str | None] = mapped_column(comment="源更新时间原始文本，时区未确认；可空")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="本系统实际采集时间，带时区")


Index(
    "ix_account_entrusts_account_curr_date",
    AccountEntrust.account_id,
    AccountEntrust.curr_date,
)
Index(
    "ix_account_entrusts_instrument_curr_date",
    AccountEntrust.instrument_code,
    AccountEntrust.curr_date,
)
Index(
    "ix_account_holdings_account_date",
    AccountHoldingSnapshot.account_id,
    AccountHoldingSnapshot.data_date,
)


class ResearchFactor(Base):
    """供用户观察和理解的市场因子目录项。"""

    __tablename__ = "research_factors"
    __table_args__: ClassVar[dict] = {"comment": "代码实现的可观察市场事件和状态目录；不保存可执行算法或因子版本"}
    factor_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="稳定因子身份，关联代码中的因子计算实现")
    factor_name: Mapped[str] = mapped_column(String(100), comment="因子中文名称，用于图例、悬停和策略说明")
    category: Mapped[str] = mapped_column(String(40), comment="因子业务分类，例如结构确认、趋势转折、突破事件、超跌状态或反转确认")
    output_type: Mapped[str] = mapped_column(String(16), comment="因子输出类型：event表示确认事件，state表示进入状态时的标记")
    meaning: Mapped[str] = mapped_column(comment="面向用户的输出含义及非买卖指令说明，不包含可执行表达式")
    chart_visible: Mapped[bool] = mapped_column(default=True, comment="是否允许在行情日K图提供显示标记")


class ResearchStrategyFactor(Base):
    """说明策略由哪些因子参与，不承担条件求值。"""

    __tablename__ = "research_strategy_factors"
    __table_args__: ClassVar[tuple] = (
        Index("ix_research_strategy_factors_factor_id", "factor_id"),
        {"comment": "当前策略与观察因子的组成关系；计算顺序和规则由代码负责"},
    )
    strategy_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="代码目录中的当前策略身份；算法实现不入库")
    factor_id: Mapped[str] = mapped_column(ForeignKey("research_factors.factor_id"), primary_key=True, comment="策略使用的因子稳定身份")
    role: Mapped[str] = mapped_column(String(24), comment="因子在策略中的作用：trigger、confirmation、filter、exit或risk")
    display_order: Mapped[int] = mapped_column(comment="策略说明中因子关系的展示顺序，从0开始")


class InstrumentStrategyAssignment(Base):
    """用户明确采用的每只ETF当前策略分配。"""

    __tablename__ = "instrument_strategy_assignments"
    __table_args__: ClassVar[tuple] = (
        Index("uq_instrument_strategy_assignment", "instrument_code", unique=True),
        {"comment": "每只ETF唯一当前策略分配；未采用时无记录，暂停不清除历史信号"},
    )
    assignment_id: Mapped[int] = mapped_column(primary_key=True, comment="当前策略分配唯一编号；更换策略时保持分配身份")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), comment="可交易ETF六位代码；每只ETF至多一条当前分配")
    strategy_id: Mapped[str] = mapped_column(String(64), comment="当前采用的服务端策略身份；仅研究策略不可分配")
    active: Mapped[bool] = mapped_column(default=True, comment="是否为该ETF生成后续盘前计划；false表示暂停")
    comparison_id: Mapped[int] = mapped_column(ForeignKey("strategy_comparisons.comparison_id"), comment="用户据以采用该策略的成功比较记录")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="当前分配首次采用或替换的本地时间，带时区")
    settings_snapshot: Mapped[dict] = mapped_column(JSON, comment="采用时账户本金、交易成本和模型状态起点；不是可选历史策略版本")


class StrategySignal(Base):
    """当前策略分配在尚未开盘时生成的唯一执行计划。"""

    __tablename__ = "strategy_signals"
    __table_args__: ClassVar[tuple] = (
        Index("uq_strategy_signal_assignment_day", "assignment_id", "execution_date", unique=True),
        {"comment": "ETF逐日策略计划与生成时证据；提示、人工确认和真实成交分开，不回填历史信号"},
    )
    signal_id: Mapped[int] = mapped_column(primary_key=True, comment="日计划唯一编号")
    assignment_id: Mapped[int] = mapped_column(ForeignKey("instrument_strategy_assignments.assignment_id"), comment="产生计划时所属的ETF当前策略分配编号")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), comment="计划对应可交易ETF六位代码")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="首次生成时间，带时区；同一分配同一执行日重复请求不修改")
    data_cutoff: Mapped[Date] = mapped_column(comment="决策所用完整行情最后交易日，不晚于生成时已采集数据")
    execution_date: Mapped[Date] = mapped_column(comment="最早执行的尚未开盘交易日；不表示实际成交日")
    plan_snapshot: Mapped[dict] = mapped_column(JSON, comment="冻结计划JSON：方向、研究目标比例份额、实际及可用份额、数据源日期、原因、因子、输入摘要和待资金核对提示")
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, comment="决策证据JSON：策略身份、规则与采用时刻、当时的行情权益、采集时刻及账户证据；不使用后来修订覆盖")
    skip_note: Mapped[str | None] = mapped_column(comment="用户明确不执行的原因；空表示未主动跳过，不等于未成交证明")
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="人工跳过确认时间，带时区；未跳过为空")


class StrategyExecutionLink(Base):
    """人工关联累计委托，不将委托时间冒充逐笔成交时间。"""

    __tablename__ = "strategy_execution_links"
    __table_args__: ClassVar[tuple] = (
        ForeignKeyConstraint(["account_id", "curr_date", "entrust_no"], ["account_entrusts.account_id", "account_entrusts.curr_date", "account_entrusts.entrust_no"]),
        Index("uq_strategy_execution_entrust", "account_id", "curr_date", "entrust_no", unique=True),
        {"comment": "真实累计委托与计划的人工确认关联；一条委托最多归属一个计划，源数量修订后重新核对"},
    )
    execution_link_id: Mapped[int] = mapped_column(primary_key=True, comment="执行关联唯一编号")
    signal_id: Mapped[int] = mapped_column(ForeignKey("strategy_signals.signal_id"), comment="人工确认对应的日计划编号")
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.account_id"), comment="本地账户编号，不是资金账号")
    curr_date: Mapped[Date] = mapped_column(comment="源委托关联日期，与account_id及entrust_no共同定位累计委托")
    entrust_no: Mapped[str] = mapped_column(String(32), comment="源累计委托号；不代表逐笔成交编号")
    confirmed_trade_date: Mapped[Date] = mapped_column(comment="用户依据对账资料确认的实际成交日期，必须等于计划执行日")
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="人工关联确认时间，带时区；不当作成交时间")
    confirmed_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), comment="确认时源累计成交份额快照，份；源后续变化用于展示修订差异")
    confirmation_note: Mapped[str] = mapped_column(comment="人工确认依据或偏离说明，不可空白；不包含自动下单含义")


class StrategyComparison(Base):
    """冻结当前策略的统一假设、数据及成功失败结果。"""

    __tablename__ = "strategy_comparisons"
    __table_args__: ClassVar[dict] = {"comment": "单ETF当前策略统一比较记录；保存本次研究证据，不构成可选择的策略版本"}
    comparison_id: Mapped[int] = mapped_column(primary_key=True, comment="本次统一比较的唯一编号")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), comment="比较的唯一可交易ETF证券代码")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="比较完成并保存的带时区本地时间")
    input_sha256: Mapped[str] = mapped_column(String(64), comment="本次比较全部策略身份、共同假设与市场输入规范JSON的SHA256摘要")
    input_snapshot: Mapped[dict] = mapped_column(JSON, comment="不可变JSON：settings统一区间本金费用、candidates当前策略身份、market行情权益日历、external外部指标及引擎/数据摘要")
    result_snapshot: Mapped[dict] = mapped_column(JSON, comment="不可变JSON：tracks策略与持有参照的状态、原因、回测编号、日权益成交分红绩效及平仓诊断")


class StrategyComparisonFactor(Base):
    """记录一次比较中各策略轨道实际引用的因子身份。"""

    __tablename__ = "strategy_comparison_factors"
    __table_args__: ClassVar[dict] = {"comment": "单次比较轨道与实际使用因子的关系；仅研究引用记录，不保存因子代码版本"}
    comparison_id: Mapped[int] = mapped_column(ForeignKey("strategy_comparisons.comparison_id"), primary_key=True, comment="所属策略比较记录")
    strategy_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="本轨道运行的代码目录策略身份")
    factor_id: Mapped[str] = mapped_column(ForeignKey("research_factors.factor_id"), primary_key=True, comment="本轨道实际使用的因子身份")
