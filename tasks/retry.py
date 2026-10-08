from config.redis import MAX_RETRY


def should_retry(retry_count: int, max_retry: int = None) -> bool:
    if max_retry is None:
        max_retry = MAX_RETRY
    return retry_count < max_retry


def get_retry_count(task) -> int:
    try:
        return getattr(task, 'retry_count', 0) or 0
    except Exception:
        return 0
