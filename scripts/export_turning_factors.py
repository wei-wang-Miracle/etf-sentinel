"""从冻结行情导出服务端统一顶底确认因子，供离线研究复核。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.algorithm_templates import TURNING_VERSION, turning_events, turning_profile


def export(directory):
    """读取冻结输入，为每只ETF输出当前统一因子的确认事件。"""
    directory = Path(directory)
    history = json.loads((directory / "input.json").read_text())
    output = {}
    for code, item in history.items():
        profile = turning_profile(code)
        events = turning_events(
            item["rows"],
            item["actions"]["dividends"],
            profile["parameters"],
        )
        output[code] = {
            "version": TURNING_VERSION,
            "profile": profile,
            "signals": [
                {"date": day, "kind": kind}
                for day, kind in events.items()
            ],
        }
    (directory / "turning.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    return output


if __name__ == "__main__":
    export(Path(sys.argv[1]))
