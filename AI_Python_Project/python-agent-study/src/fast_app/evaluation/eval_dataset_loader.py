import json
from pathlib import Path

from fast_app.evaluation.eval_case_models import RagEvalDataset


def load_eval_dataset(path: str | Path) -> RagEvalDataset:
    dataset_path = Path(path)
    raw_data = json.loads(dataset_path.read_text(encoding="utf-8"))

    return RagEvalDataset.model_validate(raw_data)
