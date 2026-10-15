from collections import defaultdict
import random
import statistics


def divide(numerator, denominator):
    return numerator / denominator if denominator else None


def confusion_metrics(*, tp, fp, tn, fn):
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": divide(tp, tp + fp), "recall": divide(tp, tp + fn),
            "f1": divide(2 * tp, 2 * tp + fp + fn),
            "false_sufficient_rate": divide(fn, tp + fn)}


def summarize(rows, *, expected_count):
    if len(rows) > expected_count:
        raise ValueError("观测数量大于预注册分母")
    counts = dict(tp=0, fp=0, tn=0, fn=0)
    for row in rows:
        predicted, true = row.get("predicted_research"), row.get("need_research")
        if predicted is None or true is None:
            continue
        counts["tp" if predicted and true else "fp" if predicted else "fn" if true else "tn"] += 1
    return {"expected_runs": expected_count, "observed_runs": len(rows),
            "missing_runs": expected_count - len(rows),
            "task_success": divide(sum(row.get("success") is True for row in rows), expected_count),
            "grading_missing": sum(row.get("grade_missing", False) for row in rows),
            "decision_missing": expected_count - sum(counts.values()),
            "confusion": confusion_metrics(**counts),
            **{f"mean_{field}": (statistics.mean(row[field] for row in rows) if rows and all(row.get(field) is not None for row in rows) and len(rows) == expected_count else None)
               for field in ("search_calls", "runtime_input_tokens", "runtime_output_tokens", "runtime_latency_ms", "steps", "judge_input_tokens", "judge_output_tokens", "judge_latency_ms")}}


def paired_bootstrap(baseline, candidate, expected, *, iterations=1000, seed=20261015):
    expected_keys = {(case, repeat) for case, _, repeat in expected}
    if set(baseline) != expected_keys or set(candidate) != expected_keys or not expected_keys:
        return {"available": False, "reason": "预注册配对不完整", "mean_difference": None, "lower": None, "upper": None}
    clusters = defaultdict(list)
    for case, topic, repeat in expected:
        clusters[topic].append(candidate[(case, repeat)] - baseline[(case, repeat)])
    means = [statistics.mean(values) for _, values in sorted(clusters.items())]
    rng = random.Random(seed)
    draws = sorted(statistics.mean(rng.choices(means, k=len(means))) for _ in range(iterations))
    return {"available": True, "mean_difference": statistics.mean(means),
            "lower": draws[int((iterations - 1) * .025)], "upper": draws[int((iterations - 1) * .975)],
            "clusters": len(means), "iterations": iterations, "seed": seed}
