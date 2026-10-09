"""Keep support checks small while requiring a decision for every proposition."""
import json
from backend.models.review_llm import verification_schema, ReviewModelError


def verify_batches(checker, model, system, items, payload, cancelled, batch_size=5):
    decisions = []
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        result = model.model_validate(checker.complete([
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': json.dumps(payload(batch), ensure_ascii=False)},
        ], verification_schema(model, batch), cancelled))
        ids = [str(d.id) for d in result.decisions]
        if len(ids) != len(set(ids)) or set(ids) != {str(i['id']) for i in batch}:
            raise ReviewModelError('MODEL_INVALID_VERIFICATION', 'Verification omitted or duplicated items. Retry the task.')
        decisions.extend(result.decisions)
    return model(decisions=decisions)
