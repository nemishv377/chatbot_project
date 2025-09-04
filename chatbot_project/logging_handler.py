import logging
import os


def set_log_file_handler(name, filepath, filename):
    logger = logging.getLogger(name)
    if not os.path.exists(filepath):
        os.makedirs(filepath)

    fileh = logging.FileHandler(os.path.join(filepath, filename), "a")

    # Add a StreamHandler for console output
    streamh = logging.StreamHandler()
    for hdlr in logger.handlers[:]:  # remove all old handlers
        logger.removeHandler(hdlr)

    # Add the File & Stream Handler to the logger
    logger.addHandler(fileh)
    logger.addHandler(streamh)

    # Format for the logging
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Set formatter for file and stream output
    fileh.setFormatter(formatter)
    streamh.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    return logger
