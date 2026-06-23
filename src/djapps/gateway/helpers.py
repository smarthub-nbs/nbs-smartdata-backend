from django.db.models import DateTimeField, Max
from django.db.models.functions import Coalesce, Greatest


def annotate_dataset_last_changed(queryset):
    base_timestamp = Coalesce(
        "updated_at",
        "created_at",
        output_field=DateTimeField(),
    )
    return queryset.annotate(
        last_changed_at=Greatest(
            base_timestamp,
            Coalesce("published_at", base_timestamp, output_field=DateTimeField()),
            Coalesce(Max("metadata__updated_at"), base_timestamp, output_field=DateTimeField()),
            Coalesce(Max("versions__updated_at"), base_timestamp, output_field=DateTimeField()),
            Coalesce(Max("versions__files__updated_at"), base_timestamp, output_field=DateTimeField()),
            Coalesce(Max("dataset_tags__updated_at"), base_timestamp, output_field=DateTimeField()),
            Coalesce(Max("status_history__changed_at"), base_timestamp, output_field=DateTimeField()),
            output_field=DateTimeField(),
        )
    )


def infer_value_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "string"


def infer_column_schema(columns, rows):
    schema = []
    for column in columns:
        observed_types = []
        for row in rows:
            value_type = infer_value_type(row.get(column))
            if value_type not in observed_types:
                observed_types.append(value_type)

        non_null_types = [value_type for value_type in observed_types if value_type != "null"]
        if not non_null_types:
            column_type = "null"
        elif len(non_null_types) == 1:
            column_type = non_null_types[0]
        else:
            column_type = "mixed"

        schema.append(
            {
                "name": column,
                "type": column_type,
                "observed_types": observed_types,
                "nullable": "null" in observed_types,
            }
        )
    return schema


def build_schema_payload(dataset_file, structured_payload):
    structure_type = structured_payload["structure_type"]
    payload = {
        "file_id": dataset_file.id,
        "filename": dataset_file.filename,
        "file_format": dataset_file.file_format,
        "structure_type": structure_type,
        "warnings": structured_payload.get("warnings", []),
    }

    if structure_type == "document":
        document = structured_payload.get("document") or {}
        payload["page_count"] = document.get("page_count", 0)
        payload["document"] = {
            "page_count": document.get("page_count", 0),
            "text_extractable": any((page.get("text") or "").strip() for page in document.get("pages", [])),
            "sample_pages": [page.get("page_number") for page in document.get("pages", [])],
            "text_excerpt": document.get("text_excerpt", ""),
        }
        return payload

    rows = structured_payload.get("rows", [])
    columns = structured_payload.get("columns", [])
    payload.update(
        {
            "column_count": len(columns),
            "row_count": structured_payload.get("total_rows", 0),
            "columns": infer_column_schema(columns, rows),
        }
    )
    if "sdmx" in structured_payload:
        payload["sdmx"] = structured_payload["sdmx"]
    return payload


def build_preview_payload(dataset_file, structured_payload):
    preview_payload = {
        "file_id": dataset_file.id,
        "filename": dataset_file.filename,
        "file_format": dataset_file.file_format,
        **structured_payload,
    }
    preview_payload.pop("data", None)
    return preview_payload
