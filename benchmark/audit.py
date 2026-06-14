"""
对账已有 JSON 数据,检测哪些任务有 Critic 数据缺失嫌疑。

用法:
    uv run python -m benchmark.audit
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"


def audit_metrics():
    """根据已有 JSON 文件,人工检测对账"""
    print("=" * 70)
    print("🔍 Critic Data Gap Audit Report")
    print("=" * 70)
    
    # 加载所有 with_reflexion 数据
    reflexion_data = {}
    baseline_data = {}
    
    for f in RESULTS_DIR.glob("*.json"):
        if f.name == "REPORT.md":
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            
            task_id = data["task_id"]
            mode = data["mode"]
            
            # 取最新的一份(按 timestamp)
            if mode == "with_reflexion":
                if task_id not in reflexion_data or data["timestamp"] > reflexion_data[task_id]["timestamp"]:
                    reflexion_data[task_id] = data
            else:
                if task_id not in baseline_data or data["timestamp"] > baseline_data[task_id]["timestamp"]:
                    baseline_data[task_id] = data
        except Exception as e:
            print(f"❌ Failed to load {f.name}: {e}")
    
    # 对账
    print(f"\n📊 Auditing {len(reflexion_data)} with_reflexion runs:\n")
    
    gaps = []
    
    for task_id, refl in sorted(reflexion_data.items()):
        scores = refl.get("critic_scores", [])
        token_refl = refl.get("token_input", 0)
        token_base = baseline_data.get(task_id, {}).get("token_input", 0)
        
        # 判断 Critic 是否被实际调用
        # 启发式 1:scores 不为空 → 明确调用了
        # 启发式 2:token 显著高于 baseline (>= 15%) → 强烈怀疑调用了
        critic_invoked_likely = bool(scores) or (token_base > 0 and token_refl >= token_base * 1.15)
        
        status = ""
        if scores:
            status = f"✅ OK    | scores={scores}"
        elif critic_invoked_likely:
            token_pct = (token_refl / token_base - 1) * 100 if token_base else 0
            status = f"⚠️ GAP   | scores=[] but token +{token_pct:.0f}% → Critic likely ran, score lost"
            gaps.append((task_id, token_pct))
        else:
            status = f"❓ UNCLEAR| scores=[] and token within baseline range"
        
        print(f"  {task_id:12} | {status}")
    
    print("\n" + "=" * 70)
    if gaps:
        print(f"🚨 Detected {len(gaps)} data gaps:")
        for task_id, pct in gaps:
            print(f"   - {task_id}: token overhead +{pct:.0f}% suggests Critic ran but score not captured")
        print(f"\n   Root cause hypothesis: race condition or fallback path not writing to ActionEvent.critic_result")
        print(f"   Mitigation: metrics.py now has _detect_critic_data_gap() to monitor future runs")
    else:
        print("✅ No data gaps detected in current dataset")
    print("=" * 70)


if __name__ == "__main__":
    audit_metrics()