"""校验离线研究导出的顶底事件来自服务端统一因子。"""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.algorithm_templates import TURNING_VERSION, turning_events, turning_profile
from export_turning_factors import export


def rows():
    return [
        {
            "trade_date": str(date(2025, 1, 1) + timedelta(days=index)),
            "open": str(10 - min(index, 70) * .025 + max(0, index - 70) * .07),
            "high": str(10.1 - min(index, 70) * .025 + max(0, index - 70) * .07),
            "low": str(9.9 - min(index, 70) * .025 + max(0, index - 70) * .07),
            "close": str(10 - min(index, 70) * .025 + max(0, index - 70) * .07),
            "volume": "10000",
        }
        for index in range(150)
    ]


def test_export_uses_the_same_etf_profile_as_the_service(tmp_path):
    history = {"510500": {"rows": rows(), "actions": {"dividends": []}}}
    (tmp_path / "input.json").write_text(json.dumps(history))

    exported = export(tmp_path)

    profile = turning_profile("510500")
    expected = turning_events(history["510500"]["rows"], [], profile["parameters"])
    assert exported["510500"] == {
        "version": TURNING_VERSION,
        "profile": profile,
        "signals": [{"date": day, "kind": kind} for day, kind in expected.items()],
    }
    assert json.loads((tmp_path / "turning.json").read_text()) == exported
