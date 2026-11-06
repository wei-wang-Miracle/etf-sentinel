"""统一数据库语义命名，并为所有业务表及字段添加说明；保留既有数据。"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

RENAMES = {
    "instruments": {
        "code": "instrument_code",
        "name": "instrument_name",
        "enabled": "collection_enabled",
        "start_date": "collection_start_date",
    },
    "candles": {
        "code": "instrument_code",
        "date": "trade_date",
        "open": "open_price",
        "high": "high_price",
        "low": "low_price",
        "close": "close_price",
        "volume": "trading_volume",
        "amount": "trading_amount",
        "change_pct": "price_change_pct",
        "adjusted_close": "adjusted_close_price",
    },
    "jobs": {"id": "job_id", "enabled": "schedule_enabled", "time": "scheduled_time"},
    "runs": {
        "id": "run_id",
        "status": "run_status",
        "trigger": "trigger_type",
        "logs": "collection_logs",
    },
    "collection_windows": {
        "code": "instrument_code",
        "start": "collection_start_date",
        "end": "collection_end_date",
    },
}
COMMENTS = {
    "instruments": (
        "ETF研究标的及采集配置；停用不删除已入库行情",
        {
            "instrument_code": "ETF证券代码，六位字符串，保留前导零；首期固定五只",
            "instrument_name": "ETF名称，来自行情源的STOCK_NAME；采集前为名称待采集",
            "collection_enabled": "是否启用后续行情采集；不影响历史行情查询",
            "collection_start_date": "历史采集起始日期，含当日；调早回补，调晚不删除历史",
        },
    ),
    "candles": (
        "ETF历史日行情；按证券代码和交易日期唯一，源修订幂等覆盖",
        {
            "instrument_code": "ETF证券代码，关联instruments.instrument_code",
            "trade_date": "数据源交易日期，非采集日期；按源值保存",
            "open_price": "原始日开盘价，人民币元；未推断复权口径",
            "high_price": "原始日最高价，人民币元；未推断复权口径",
            "low_price": "原始日最低价，人民币元；未推断复权口径",
            "close_price": "原始日收盘价，人民币元；未推断复权口径",
            "trading_volume": "日成交量，保留源数值；单位待数据源确认",
            "trading_amount": "日成交额，保留源数值；单位待数据源确认",
            "price_change_pct": "相对昨收涨跌幅，百分数单位，如1表示1%",
            "adjusted_close_price": "源ADJUSTED_CLOSE复权收盘值；前后复权类型尚未确认；可空",
            "source_updated_at": "数据源更新时间原始文本；源时区未确认；可空",
            "collected_at": "本系统成功采集时间，带时区时间戳",
        },
    ),
    "jobs": (
        "日行情采集任务配置；执行时区Asia/Shanghai",
        {
            "job_id": "采集任务唯一编号；当前ETF日行情任务固定为1",
            "schedule_enabled": "是否启用每日调度；不禁止手动触发",
            "scheduled_time": "每日北京时间执行时刻，24小时HH:mm格式",
            "last_scheduled_date": "最近一次成功触发定时运行的北京时间日期；非采集完成日；可空",
        },
    ),
    "runs": (
        "采集任务运行记录；保留运行状态及不含凭据的区间日志",
        {
            "run_id": "单次采集运行唯一编号，自增主键",
            "run_status": "运行状态：running运行中、success成功、partial部分失败、failed失败、interrupted中断",
            "trigger_type": "触发方式：manual手动、scheduled定时",
            "started_at": "运行开始时间，带时区时间戳",
            "ended_at": "运行结束或中断时间，带时区时间戳；运行中为空",
            "collection_logs": "区间日志JSON数组；元素含code标的、start/end请求闭区间、status、count返回条数、message安全摘要；不保存凭据",
        },
    ),
    "collection_windows": (
        "已成功查询的历史区间；空响应也记录，复查失败撤销进度以便重试",
        {
            "instrument_code": "ETF证券代码，关联instruments.instrument_code",
            "collection_start_date": "成功查询区间起始日期，含当日；与instrument_code组成主键",
            "collection_end_date": "成功查询区间截止日期，含当日；不代表区间交易日完整性已验证",
        },
    ),
}


def upgrade():
    """原地重命名列并补充数据库注释。"""
    for table, columns in RENAMES.items():
        for old, new in columns.items():
            op.alter_column(table, old, new_column_name=new)
    for table, (description, columns) in COMMENTS.items():
        op.create_table_comment(table, description)
        for column, description in columns.items():
            op.alter_column(table, column, comment=description)


def downgrade():
    """撤销注释与命名修正，不删除业务数据。"""
    for table, (_, columns) in COMMENTS.items():
        op.drop_table_comment(table)
        for column in columns:
            op.alter_column(table, column, comment=None)
    for table, columns in reversed(list(RENAMES.items())):
        for old, new in columns.items():
            op.alter_column(table, new, new_column_name=old)
