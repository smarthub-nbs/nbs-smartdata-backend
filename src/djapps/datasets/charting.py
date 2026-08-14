from collections import OrderedDict

from rest_framework.exceptions import ValidationError

from djapps.datasets.geo_tree import filter_geo_rows, parse_area_levels


SUPPORTED_CHART_TYPES = ("bar", "pie", "line", "scatter")
SUPPORTED_CHART_METRICS = ("count", "sum", "avg", "min", "max")


def _simplify_number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _normalize_label(value):
    if value is None or value == "":
        return "(blank)"
    return str(value)


def _coerce_number(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _simplify_number(value)
    if isinstance(value, str):
        normalized = value.strip().replace(",", "")
        if not normalized:
            return None
        try:
            numeric_value = float(normalized)
        except ValueError:
            return None
        return _simplify_number(numeric_value)
    return None


def _validate_field(columns, field_name):
    if field_name and columns and field_name not in columns:
        raise ValidationError({field_name: ["This field does not exist in the file."]})


def _aggregate_values(values, metric):
    numeric_values = [value for value in values if value is not None]
    if not numeric_values:
        return None
    if metric == "sum":
        return _simplify_number(sum(numeric_values))
    if metric == "avg":
        return _simplify_number(sum(numeric_values) / len(numeric_values))
    if metric == "min":
        return _simplify_number(min(numeric_values))
    if metric == "max":
        return _simplify_number(max(numeric_values))
    return len(numeric_values)


def _sort_points(points, chart_type, sort):
    reverse = sort == "desc"

    if chart_type == "scatter":
        return sorted(
            points,
            key=lambda point: (
                point["x"] is None,
                point["x"] if isinstance(point["x"], (int, float)) else str(point["x"]),
                point["y"] if isinstance(point["y"], (int, float)) else str(point["y"]),
            ),
            reverse=reverse,
        )

    if chart_type == "line":
        return sorted(
            points,
            key=lambda point: (
                point["x"] is None,
                point["x"] if isinstance(point["x"], (int, float)) else str(point["x"]),
                point["label"],
            ),
            reverse=reverse,
        )

    return sorted(
        points,
        key=lambda point: (
            point["value"] is None,
            point["value"] if isinstance(point["value"], (int, float)) else str(point["value"]),
            point["label"],
        ),
        reverse=reverse,
    )


def build_dataset_chart_payload(
    dataset_file,
    structured_payload,
    *,
    chart_type,
    x_field,
    y_field=None,
    group_by=None,
    metric="count",
    sort=None,
    limit=20,
    area_level=None,
    parent_code=None,
    area_code_prefix=None,
    key_field=None,
):
    if structured_payload.get("structure_type") == "document":
        raise ValidationError(
            {"file": ["Chart generation is not supported for PDF documents."]}
        )

    rows = structured_payload.get("rows") or []
    columns = structured_payload.get("columns") or []
    warnings = list(structured_payload.get("warnings") or [])
    rows = filter_geo_rows(
        rows,
        area_levels=parse_area_levels(area_level),
        parent_code=parent_code,
        area_code_prefix=area_code_prefix,
    )

    if not rows:
        geo_filtered = bool(area_level or parent_code or area_code_prefix)
        if not geo_filtered:
            raise ValidationError(
                {"file": ["No structured rows are available for charting."]}
            )
        dimension_field = group_by or x_field
        warnings.append("No rows matched the geographic filter.")
        return {
            "file_id": dataset_file.id,
            "filename": dataset_file.filename,
            "file_format": dataset_file.file_format,
            "structure_type": structured_payload.get("structure_type"),
            "chart_type": chart_type,
            "x_field": x_field,
            "y_field": y_field,
            "group_by": group_by,
            "metric": metric,
            "columns": columns,
            "series": [
                {
                    "name": f"{metric} of {y_field}" if y_field else "count",
                    "field": dimension_field,
                    "points": [],
                }
            ],
            "point_count": 0,
            "source_row_count": 0,
            "warnings": warnings,
        }

    if chart_type not in SUPPORTED_CHART_TYPES:
        raise ValidationError(
            {"chart_type": [f"Unsupported chart type. Use one of: {', '.join(SUPPORTED_CHART_TYPES)}."]}
        )

    if metric not in SUPPORTED_CHART_METRICS:
        raise ValidationError(
            {"metric": [f"Unsupported metric. Use one of: {', '.join(SUPPORTED_CHART_METRICS)}."]}
        )

    if chart_type == "scatter":
        _validate_field(columns, x_field)
        _validate_field(columns, y_field)
        if not x_field or not y_field:
            raise ValidationError(
                {"detail": ["Scatter charts require both x_field and y_field."]}
            )
        points = []
        skipped_rows = 0
        for row in rows:
            x_value = _coerce_number(row.get(x_field))
            y_value = _coerce_number(row.get(y_field))
            if x_value is None or y_value is None:
                skipped_rows += 1
                continue
            points.append(
                {
                    "label": None,
                    "x": x_value,
                    "y": y_value,
                    "value": None,
                    "count": 1,
                }
            )

        if skipped_rows:
            warnings.append(f"Skipped {skipped_rows} row(s) that did not contain numeric scatter values.")

        if not points:
            raise ValidationError(
                {"detail": ["No numeric points could be extracted for the scatter chart."]}
            )

        sorted_points = _sort_points(points, chart_type, sort or "asc")
        limited_points = sorted_points[:limit] if limit is not None else sorted_points
        return {
            "file_id": dataset_file.id,
            "filename": dataset_file.filename,
            "file_format": dataset_file.file_format,
            "structure_type": structured_payload["structure_type"],
            "chart_type": chart_type,
            "x_field": x_field,
            "y_field": y_field,
            "group_by": group_by,
            "metric": metric,
            "columns": columns,
            "series": [
                {
                    "name": f"{y_field} vs {x_field}",
                    "field": None,
                    "points": limited_points,
                }
            ],
            "point_count": len(limited_points),
            "source_row_count": len(rows),
            "warnings": warnings,
        }

    dimension_field = group_by or x_field
    if not dimension_field:
        raise ValidationError({"x_field": ["This field is required for bar, pie, and line charts."]})

    _validate_field(columns, dimension_field)
    if y_field:
        _validate_field(columns, y_field)
    if key_field:
        _validate_field(columns, key_field)
    if metric != "count" and not y_field:
        raise ValidationError(
            {"y_field": ["This field is required when using sum, avg, min, or max metrics."]}
        )

    grouped_rows = OrderedDict()
    for row in rows:
        label = _normalize_label(row.get(dimension_field))
        bucket = grouped_rows.setdefault(
            label,
            {
                "label": label,
                "count": 0,
                "values": [],
                "key": None,
            },
        )
        bucket["count"] += 1
        if key_field and bucket["key"] is None:
            bucket["key"] = _normalize_label(row.get(key_field))
            if bucket["key"] == "(blank)":
                bucket["key"] = None
        if metric != "count":
            bucket["values"].append(_coerce_number(row.get(y_field)))

    points = []
    for bucket in grouped_rows.values():
        aggregated_value = bucket["count"] if metric == "count" else _aggregate_values(bucket["values"], metric)
        point = {
            "label": bucket["label"],
            "x": bucket["label"],
            "y": aggregated_value,
            "value": aggregated_value,
            "count": bucket["count"],
        }
        if key_field:
            point["key"] = bucket["key"]
        points.append(point)

    if not points:
        raise ValidationError({"detail": ["No chart points could be generated from the dataset."]})

    default_sort = "asc" if chart_type == "line" else "desc"
    sorted_points = _sort_points(points, chart_type, sort or default_sort)
    limited_points = sorted_points[:limit] if limit is not None else sorted_points

    return {
        "file_id": dataset_file.id,
        "filename": dataset_file.filename,
        "file_format": dataset_file.file_format,
        "structure_type": structured_payload["structure_type"],
        "chart_type": chart_type,
        "x_field": x_field,
        "y_field": y_field,
        "group_by": group_by,
        "metric": metric,
        "columns": columns,
        "series": [
            {
                "name": f"{metric} of {y_field}" if y_field else "count",
                "field": dimension_field,
                "points": limited_points,
            }
        ],
        "point_count": len(limited_points),
        "source_row_count": len(rows),
        "warnings": warnings,
    }
