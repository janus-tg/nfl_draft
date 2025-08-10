import logging
import os


# Configure a reusable application logger
logger = logging.getLogger("nfl_draft")
if not logger.handlers:
    logger.setLevel(logging.INFO)

    # Ensure logs directory exists
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "nfl_draft.log")
    except Exception:
        # Fallback to current directory if logs folder can't be created
        log_file_path = os.path.join(os.path.dirname(__file__), "nfl_draft.log")

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
