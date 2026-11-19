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
    text,
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
        comment="采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划",
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
        comment="所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划",
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


class StrategyResearchBatch(Base):
    """冻结用户采用的算法模板及其来源，数据不随行情同步改写。"""

    __tablename__ = "strategy_research_batches"
    __table_args__: ClassVar[dict] = {"comment": "ETF算法模板采用记录批次；冻结模板版本、回测来源及采用时间，不表示真实成交"}
    research_batch_id: Mapped[int] = mapped_column(primary_key=True, comment="本地研究批次唯一编号")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="研究创建时间，带时区")
    input_snapshot: Mapped[dict] = mapped_column(JSON, comment="冻结采用输入JSON：模板保存版本编号、回测设置与引擎版本；不含真实账户本金")
    result_snapshot: Mapped[dict] = mapped_column(JSON, comment="冻结采用结果JSON：关联比较编号、回测编号及后续观察状态")
    input_sha256: Mapped[str] = mapped_column(String(64), comment="规范输入快照SHA256，核查研究假设未被修改")


class StrategyObservation(Base):
    """用户明确采用的不可变算法模板版本，暂停仅停止新信号。"""

    __tablename__ = "strategy_observations"
    __table_args__: ClassVar[tuple] = (
        Index("uq_strategy_observation_active", "instrument_code", unique=True, postgresql_where=text("active")),
        {"comment": "ETF算法模板观察版本；采用不代表已下单或实际成交，更新模板需新建版本"},
    )
    observation_id: Mapped[int] = mapped_column(primary_key=True, comment="观察版本唯一编号")
    strategy_version_id: Mapped[int | None] = mapped_column(ForeignKey("saved_strategy_versions.strategy_version_id"), nullable=True, comment="采用的算法模板保存版本编号；NULL表示已退役的旧持仓候选观察")
    research_batch_id: Mapped[int] = mapped_column(ForeignKey("strategy_research_batches.research_batch_id"), comment="模板采用记录所属研究批次编号")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), comment="可交易ETF六位代码，指数不得作为观察对象")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="用户采用时间，带时区；此前历史不算前向业绩")
    active: Mapped[bool] = mapped_column(default=True, comment="是否继续生成新计划；暂停不修改历史规则及信号")
    rule_snapshot: Mapped[dict] = mapped_column(JSON, comment="不可变模板JSON：模板标识和版本、算法及顶底版本、ETF冻结参数、模型状态起点、研究本金与成本；不含真实账户本金")


class StrategySignal(Base):
    """某个观察版本在尚未开盘时生成的唯一执行计划。"""

    __tablename__ = "strategy_signals"
    __table_args__: ClassVar[tuple] = (
        Index("uq_strategy_signal_observation_day", "observation_id", "execution_date", unique=True),
        {"comment": "ETF逐日观察计划与生成时证据；提示、人工确认和真实成交分开，不回填历史信号"},
    )
    signal_id: Mapped[int] = mapped_column(primary_key=True, comment="日计划唯一编号")
    observation_id: Mapped[int] = mapped_column(ForeignKey("strategy_observations.observation_id"), comment="产生计划的不可变观察版本编号")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), comment="计划对应可交易ETF六位代码")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="首次生成时间，带时区；同版本同执行日重复请求不修改")
    data_cutoff: Mapped[Date] = mapped_column(comment="决策所用完整行情最后交易日，不晚于生成时已采集数据")
    execution_date: Mapped[Date] = mapped_column(comment="最早执行的尚未开盘交易日；不表示实际成交日")
    plan_snapshot: Mapped[dict] = mapped_column(JSON, comment="冻结计划JSON：方向、研究目标比例份额、实际及可用份额、数据源日期、原因、因子、输入摘要和待资金核对提示")
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, comment="决策证据JSON：当时完整行情、权益、规则版本及采集时刻，可重算；不使用后来修订覆盖")
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


class SavedStrategy(Base):
    """算法模板与可交易ETF的稳定绑定。"""

    __tablename__ = "saved_strategies"
    __table_args__: ClassVar[tuple] = (
        Index("uq_saved_strategy_etf_algorithm", "instrument_code", "algorithm_template_id", unique=True),
        {"comment": "共享算法与可交易ETF的绑定；保存不自动启用，不代表真实交易"},
    )
    strategy_id: Mapped[int] = mapped_column(primary_key=True, comment="算法与ETF绑定的稳定编号，后续不可变回测记录共用")
    algorithm_template_id: Mapped[str | None] = mapped_column(String(64), comment="服务端算法模板稳定标识，不含版本；NULL仅表示历史逐ETF规则")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), comment="绑定的可交易ETF六位证券代码，指数不可作为主体")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="首次保存策略身份的带时区本地时间")


class StrategyComparison(Base):
    """冻结同ETF算法模板的统一假设、数据及成功失败结果。"""

    __tablename__ = "strategy_comparisons"
    __table_args__: ClassVar[dict] = {"comment": "单ETF算法模板统一比较记录；包含模板版本、失败对象及研究证据类型，不覆盖既有回测或启用状态"}
    comparison_id: Mapped[int] = mapped_column(primary_key=True, comment="本次统一比较的唯一编号")
    instrument_code: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_code"), comment="比较的唯一可交易ETF证券代码")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="比较完成并保存的带时区本地时间")
    input_sha256: Mapped[str] = mapped_column(String(64), comment="规范输入JSON的SHA256，包括策略版本、共同假设及全部输入快照")
    input_snapshot: Mapped[dict] = mapped_column(JSON, comment="不可变JSON：settings统一区间本金费用、candidates模板及版本、market行情权益日历、external各日期外部指标与采集证据、引擎及算法版本")
    result_snapshot: Mapped[dict] = mapped_column(JSON, comment="不可变JSON：tracks各模板与持有参照的status成功失败、reason原因、backtest_id、account日权益成交分红绩效、完整平仓轮次及未平仓诊断；complete表示全部成功")


class SavedStrategyVersion(Base):
    """有效模板回测产生的不可变策略版本，启用状态由观察记录表示。"""

    __tablename__ = "saved_strategy_versions"
    __table_args__: ClassVar[tuple] = (
        Index("uq_saved_strategy_version", "strategy_id", "version_number", unique=True),
        {"comment": "算法模板不可变版本；模板版本、预算、费用和原回测固定，更新需保存新版本"},
    )
    strategy_version_id: Mapped[int] = mapped_column(primary_key=True, comment="算法模板策略具体版本唯一编号，与稳定strategy_id不同")
    strategy_id: Mapped[int] = mapped_column(ForeignKey("saved_strategies.strategy_id"), comment="归属策略稳定编号")
    version_number: Mapped[int] = mapped_column(comment="同一策略内从1递增的版本号")
    strategy_name: Mapped[str] = mapped_column(String(100), comment="保存时的算法中文名称；历史记录保留原名称，非收益承诺")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="版本保存时间，带时区")
    configuration: Mapped[dict] = mapped_column(JSON, comment="不可变JSON：template为冻结算法标识、版本和规则，settings为回测日期、本金、成本及ETF；历史逐ETF规则保留原快照")
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.backtest_run_id"), comment="已成功核算且规则配置相符的不可变原回测编号")
    comparison_id: Mapped[int] = mapped_column(ForeignKey("strategy_comparisons.comparison_id"), comment="产生该有效回测的统一比较编号")
