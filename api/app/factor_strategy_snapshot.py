"""分类因子策略研究的冻结输入转换与类别目录。"""

from app.research_factors import factor_truth_rows
from app.shared_etf_snapshot import build_snapshot_item

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


def category_for_code(code):
    """返回研究报告使用的资产类别，未知代码保留为待补充分组。"""
    return CATEGORY_BY_CODE.get(code, "未分类")


def independent_key(code, indices):
    """同一关联指数共享一个评分单位，未映射资产自身独立。"""
    return indices[0] if len(indices) == 1 else code


def build_factor_snapshot_item(
    *, code, name, rows, actions, indices, source, turning
):
    """构造标准化行情、因子逐日真值及类别元数据的一只研究标的。"""
    item, coverage = build_snapshot_item(
        code=code,
        name=name,
        rows=rows,
        actions=actions,
        indices=indices,
        role="full_universe",
        source=source,
    )
    item.update(
        code=code,
        category=category_for_code(code),
        independent_key=independent_key(code, item["indices"]),
        factor_truth=factor_truth_rows(item["rows"], turning, item["actions"]["dividends"]),
    )
    return item, coverage
