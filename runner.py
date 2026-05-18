"""
runner.py — evaluate every scenario against every model via OpenRouter.

Output: results/raw/{model_slug}/{scenario_id}.json
        (idempotent — skips pairs that already have a result file)
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tqdm import tqdm

MODELS = [
    "openai/gpt-4o",
    "openai/o3",
    "anthropic/claude-sonnet-4-5",
    "google/gemini-2.5-pro",
    "meta-llama/llama-4-maverick",
    "mistralai/mistral-large",
    "x-ai/grok-3",
]

SCENARIOS_FILE = Path("scenarios.json")
RESULTS_DIR = Path("results/raw")


def model_slug(model: str) -> str:
    return model.replace("/", "__")


def load_scenarios() -> list[dict]:
    data = json.loads(SCENARIOS_FILE.read_text())
    # Support both a top-level list and {"prompts": [...]} envelope
    if isinstance(data, list):
        return data
    return data.get("prompts", data)


def scenario_id_str(scenario: dict) -> str:
    sid = scenario.get("id", scenario.get("scenario_id", "unknown"))
    return str(sid).zfill(2)


def result_path(model: str, scenario: dict) -> Path:
    return RESULTS_DIR / model_slug(model) / f"{scenario_id_str(scenario)}.json"


def build_client() -> OpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is not set")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(RateLimitError),
    reraise=True,
)
def call_model(client: OpenAI, model: str, prompt: str) -> dict:
    start = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
        timeout=90,
    )
    latency_ms = int((time.monotonic() - start) * 1000)
    choice = response.choices[0]
    return {
        "response_text": choice.message.content or "",
        "finish_reason": choice.finish_reason,
        "latency_ms": latency_ms,
    }


def run_pair(client: OpenAI, model: str, scenario: dict) -> dict | None:
    path = result_path(model, scenario)
    if path.exists():
        return None  # already done

    prompt = scenario.get("prompt", scenario.get("text", ""))
    try:
        result = call_model(client, model, prompt)
    except Exception as exc:
        result = {"response_text": "", "finish_reason": "error", "latency_ms": 0, "error": str(exc)}

    record = {
        "scenario_id": scenario_id_str(scenario),
        "model": model,
        "prompt": prompt,
        **result,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2))
    return record


def print_progress_table(completed: list[tuple[str, str, int | str]]) -> None:
    if not completed:
        return
    print(f"\n{'Model':<40} {'Scenario':>10} {'Score/Status':>15}")
    print("-" * 68)
    for model, sid, status in completed[-10:]:  # show last 10
        print(f"  {model:<38} {sid:>10} {str(status):>15}")
    print()


def main() -> None:
    client = build_client()
    scenarios = load_scenarios()
    total = len(scenarios) * len(MODELS)
    completed: list[tuple[str, str, int | str]] = []

    print(f"Evaluating {len(scenarios)} scenarios × {len(MODELS)} models = {total} pairs\n")

    with tqdm(total=total, unit="pair") as pbar:
        for scenario in scenarios:
            sid = scenario_id_str(scenario)
            with ThreadPoolExecutor(max_workers=len(MODELS)) as pool:
                futures = {
                    pool.submit(run_pair, client, model, scenario): model
                    for model in MODELS
                }
                for future in as_completed(futures):
                    model = futures[future]
                    try:
                        record = future.result()
                    except Exception as exc:
                        record = None
                        tqdm.write(f"  ERROR {model} s{sid}: {exc}")
                    status = "skipped" if record is None else record.get("finish_reason", "done")
                    completed.append((model, sid, status))
                    pbar.set_description(f"{model_slug(model)[:30]} / s{sid}")
                    pbar.update(1)

    # Final summary table
    print("\n===== Evaluation complete =====")
    print(f"{'Model':<40} {'Completed':>10} {'Errors':>8}")
    print("-" * 60)
    for model in MODELS:
        slug = model_slug(model)
        model_dir = RESULTS_DIR / slug
        files = list(model_dir.glob("*.json")) if model_dir.exists() else []
        errors = sum(
            1 for f in files if "error" in json.loads(f.read_text())
        )
        print(f"  {model:<38} {len(files):>10} {errors:>8}")


if __name__ == "__main__":
    main()
