"""将国家队十八只ETF并入统一行情配置，保留原有设置和历史。"""

from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

INSTRUMENTS = {
    "510300": "华泰柏瑞沪深300ETF",
    "510330": "华夏沪深300ETF",
    "510310": "易方达沪深300ETF",
    "159919": "嘉实沪深300ETF",
    "510050": "华夏上证50ETF",
    "510180": "华安上证180ETF",
    "510500": "南方中证500ETF",
    "512500": "华夏中证500ETF",
    "159922": "嘉实中证500ETF",
    "159845": "华夏中证1000ETF",
    "512100": "南方中证1000ETF",
    "560010": "广发中证1000ETF",
    "159629": "富国中证1000ETF",
    "159915": "易方达创业板ETF",
    "159952": "广发创业板ETF",
    "159977": "天弘创业板ETF",
    "588080": "易方达科创50ETF",
    "588050": "工银科创50ETF",
}


def upgrade():
    """只插入尚未配置的基金，后续由行情源更新名称。"""
    table = sa.table(
        "instruments",
        sa.column("instrument_code"),
        sa.column("instrument_name"),
        sa.column("collection_enabled"),
        sa.column("collection_start_date"),
    )
    op.execute(
        insert(table)
        .values(
            [
                {
                    "instrument_code": code,
                    "instrument_name": name,
                    "collection_enabled": True,
                    "collection_start_date": date(2020, 1, 1),
                }
                for code, name in INSTRUMENTS.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["instrument_code"])
    )
    op.alter_column(
        "instruments",
        "instrument_code",
        comment="ETF证券代码，六位字符串，保留前导零；统一行情研究标的",
    )
    op.alter_column(
        "instruments",
        "instrument_name",
        comment="ETF名称，行情源返回后更新；国家队新增标的初始名称来自国家队目录",
    )


def downgrade():
    """保留新增配置和行情，避免降级删除用户数据。"""
    op.alter_column(
        "instruments",
        "instrument_code",
        comment="ETF证券代码，六位字符串，保留前导零；首期固定五只",
    )
    op.alter_column(
        "instruments",
        "instrument_name",
        comment="ETF名称，来自行情源的STOCK_NAME；采集前为名称待采集",
    )
