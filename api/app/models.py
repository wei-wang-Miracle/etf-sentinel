"""行情、配置及可恢复采集进度的持久化模型。"""

from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String
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
        comment="采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例",
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
        comment="所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例",
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
    __table_args__: ClassVar[dict] = {"comment": "回测现金分红与折算来源；仅支持已核实的两只境内股票ETF，不作为行情价格"}
    instrument_code: Mapped[str] = mapped_column(
        ForeignKey("instruments.instrument_code"), primary_key=True,
        comment="证券代码，关联instruments.instrument_code；当前510500或512100",
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
