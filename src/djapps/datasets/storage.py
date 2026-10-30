from rest_framework.exceptions import NotFound


MISSING_DATASET_FILE_MESSAGE = (
    "Dataset file is missing from storage. Re-upload the file or configure "
    "persistent media storage."
)


def open_dataset_file(dataset_file):
    try:
        return dataset_file.file.open("rb")
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise NotFound(MISSING_DATASET_FILE_MESSAGE) from exc
