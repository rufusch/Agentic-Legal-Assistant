"""Provider-aware excerpt budgets; retrieval reports the actual bounded scope."""
import os


def source_budget(llm,maximum):
    default=6000 if getattr(llm,'provider',None)=='groq' else maximum
    try:requested=int(os.getenv('LEXIMIND_SOURCE_CONTEXT_CHARACTERS',str(default)))
    except ValueError:raise ValueError('LEXIMIND_SOURCE_CONTEXT_CHARACTERS must be an integer.')
    if requested<1200:raise ValueError('Source context budget must be at least 1,200 characters.')
    return min(maximum,requested)
