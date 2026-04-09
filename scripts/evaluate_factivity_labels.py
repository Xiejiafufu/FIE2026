import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "sample sets" / "sample_20260401.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs"
OPENAI_API_URL = "https://api.openai.com/v1/responses"
VALID_LABELS = ("TRUE", "FALSE", "UNCERTAIN")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate factivity labels on the FIE2026 sample set with a single-turn prompt."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help=f"Path to the dataset JSON file. Default: {DEFAULT_DATASET}",
    )
    parser.add_argument(
        "--model",
        default="gpt-5.4",
        help="Model name for the OpenAI Responses API. Default: gpt-5.4",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY"),
        help="OpenAI API key. Defaults to OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--provider",
        choices=("openai", "mock"),
        default="openai",
        help="Inference backend. Use 'mock' for a local smoke test.",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Evaluate only the first N samples.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional delay between requests.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries for transient API errors.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for result files. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print each prediction as it is produced.",
    )
    return parser.parse_args()


def load_dataset(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_single_turn_prompt(text: str, hypothesis: str) -> str:
    return (
        "任务：根据给定的 text 和 hypothesis，判断 hypothesis 在 text 语境中的叙实性标签。\n"
        "只输出一个 JSON 对象，不要输出其他内容。\n"
        'JSON 格式：{"factivity":"TRUE"}\n'
        "factivity 只能是 TRUE、FALSE、UNCERTAIN 三者之一。\n\n"
        f"text: {text}\n"
        f"hypothesis: {hypothesis}"
    )


def normalize_label(value: str) -> str:
    label = value.strip().upper()
    if label not in VALID_LABELS:
        raise ValueError(f"Invalid label: {value!r}")
    return label


def extract_json_object(raw_text: str) -> dict[str, Any]:
    raw_text = raw_text.strip()
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise
        parsed = json.loads(raw_text[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError(f"Expected a JSON object, got: {type(parsed).__name__}")
    return parsed


def extract_output_text(response_json: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in response_json.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                texts.append(content.get("text", ""))
    if not texts:
        raise ValueError("No output_text found in API response.")
    return "".join(texts).strip()


@dataclass
class Prediction:
    sample_id: str
    gold: str
    pred: str
    ok: bool
    raw_output: str


class MockSingleTurnClient:
    def predict(self, text: str, hypothesis: str) -> str:
        # This branch is a local smoke test only. It simulates the model I/O shape
        # with a small set of lexical rules so the evaluation pipeline can run offline.
        del hypothesis
        text_lower = text.lower()

        false_markers = (
            "错误地认为",
            "假装",
            "吹嘘",
            "诬陷",
            "幻想",
            "梦想",
            "嫁祸",
            "并没有计划",
            "没有试图",
            "不能认同",
            "不该相信",
        )
        uncertain_markers = (
            "认为",
            "猜测",
            "担心",
            "希望",
            "不知道",
            "觉得",
            "估计",
            "推测",
            "似乎",
            "料想",
        )

        label = "TRUE"
        if any(marker in text_lower for marker in false_markers):
            label = "FALSE"
        elif any(marker in text_lower for marker in uncertain_markers):
            label = "UNCERTAIN"

        return json.dumps({"factivity": label}, ensure_ascii=False)


class OpenAIResponsesSingleTurnClient:
    def __init__(self, model: str, api_key: str, max_retries: int) -> None:
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries

    def predict(self, text: str, hypothesis: str) -> str:
        prompt = build_single_turn_prompt(text, hypothesis)
        payload = {
            "model": self.model,
            "input": prompt,
            "store": False,
            "max_output_tokens": 32,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "factivity_label",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "factivity": {
                                "type": "string",
                                "enum": list(VALID_LABELS),
                            }
                        },
                        "required": ["factivity"],
                        "additionalProperties": False,
                    },
                }
            },
        }

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            OPENAI_API_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with request.urlopen(req, timeout=120) as resp:
                    response_json = json.loads(resp.read().decode("utf-8"))
                return extract_output_text(response_json)
            except error.HTTPError as exc:
                message = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(
                    f"HTTP {exc.code} while calling OpenAI API: {message}"
                )
                if exc.code in {408, 409, 429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise last_error
            except error.URLError as exc:
                last_error = RuntimeError(f"Network error while calling OpenAI API: {exc}")
                if attempt < self.max_retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise last_error
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise

        raise RuntimeError(f"Prediction failed after retries: {last_error}")


def make_client(args: argparse.Namespace) -> Any:
    if args.provider == "mock":
        return MockSingleTurnClient()
    if not args.api_key:
        raise SystemExit(
            "Missing API key. Set OPENAI_API_KEY or pass --api-key, or use --provider mock."
        )
    return OpenAIResponsesSingleTurnClient(
        model=args.model,
        api_key=args.api_key,
        max_retries=args.max_retries,
    )


def evaluate(
    data: list[dict[str, Any]],
    client: Any,
    sleep_seconds: float,
    verbose: bool,
) -> tuple[list[Prediction], dict[str, Any]]:
    predictions: list[Prediction] = []
    confusion: dict[str, Counter[str]] = defaultdict(Counter)

    for index, item in enumerate(data, start=1):
        raw_output = client.predict(item["text"], item["hypothesis"])
        pred_obj = extract_json_object(raw_output)
        pred_label = normalize_label(pred_obj["factivity"])
        gold_label = normalize_label(item["factivity"])
        ok = pred_label == gold_label

        predictions.append(
            Prediction(
                sample_id=item["id"],
                gold=gold_label,
                pred=pred_label,
                ok=ok,
                raw_output=raw_output,
            )
        )
        confusion[gold_label][pred_label] += 1

        if verbose:
            print(
                f"[{index:03d}] {item['id']} gold={gold_label} pred={pred_label} ok={ok}",
                flush=True,
            )

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    total = len(predictions)
    correct = sum(1 for item in predictions if item.ok)
    accuracy = correct / total if total else 0.0

    per_label: dict[str, dict[str, Any]] = {}
    for label in VALID_LABELS:
        label_items = [item for item in predictions if item.gold == label]
        label_total = len(label_items)
        label_correct = sum(1 for item in label_items if item.ok)
        per_label[label] = {
            "total": label_total,
            "correct": label_correct,
            "accuracy": (label_correct / label_total) if label_total else 0.0,
        }

    summary = {
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "per_label": per_label,
        "confusion": {gold: dict(preds) for gold, preds in confusion.items()},
    }
    return predictions, summary


def save_results(
    output_dir: Path,
    dataset_path: Path,
    provider: str,
    model: str,
    predictions: list[Prediction],
    summary: dict[str, Any],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = output_dir / f"factivity_label_eval_{provider}_{model}_{timestamp}.json"
    payload = {
        "dataset": str(dataset_path),
        "provider": provider,
        "model": model,
        "summary": summary,
        "predictions": [
            {
                "id": item.sample_id,
                "gold": item.gold,
                "pred": item.pred,
                "ok": item.ok,
                "raw_output": item.raw_output,
            }
            for item in predictions
        ],
    }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return result_path


def print_summary(summary: dict[str, Any], result_path: Path) -> None:
    print(f"accuracy: {summary['accuracy']:.4f} ({summary['correct']}/{summary['total']})")
    for label in VALID_LABELS:
        stats = summary["per_label"][label]
        print(
            f"{label}: {stats['accuracy']:.4f} ({stats['correct']}/{stats['total']})"
        )
    print("confusion:")
    for gold in VALID_LABELS:
        row = summary["confusion"].get(gold, {})
        print(f"  gold={gold}: {row}")
    print(f"saved: {result_path}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    data = load_dataset(args.dataset)
    if args.max_samples is not None:
        data = data[: args.max_samples]

    client = make_client(args)
    predictions, summary = evaluate(
        data=data,
        client=client,
        sleep_seconds=args.sleep_seconds,
        verbose=args.verbose,
    )
    result_path = save_results(
        output_dir=args.output_dir,
        dataset_path=args.dataset,
        provider=args.provider,
        model=args.model.replace("/", "_"),
        predictions=predictions,
        summary=summary,
    )
    print_summary(summary, result_path)


if __name__ == "__main__":
    main()
