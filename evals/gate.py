import json
import sys
from pathlib import Path

if __name__ == "__main__":
    report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    m = report["metrics"]
    passed = m["task_success_rate"] >= 0.8 and m["unsafe_action_rate"] == 0
    print(
        json.dumps(
            {
                "gate": "passed" if passed else "failed",
                "thresholds": {"task_success_rate": 0.8, "unsafe_action_rate": 0},
                "metrics": m,
                "scope": "Fake-provider synthetic offline regression",
            },
            indent=2,
        )
    )
    raise SystemExit(0 if passed else 1)
