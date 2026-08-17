import csv
import io
import json
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader
from rest_framework.exceptions import ValidationError
import xlrd

from djapps.datasets.constants import (
    STRUCTURED_DATA_SUPPORTED_FORMATS,
    XLSX_MAIN_NS,
    XLSX_PACKAGE_REL_NS,
    XLSX_REL_NS,
)


def normalize_headers(raw_headers, width=None):
    raw_headers = list(raw_headers)
    width = width or len(raw_headers)
    if len(raw_headers) < width:
        raw_headers.extend([None] * (width - len(raw_headers)))

    seen = {}
    normalized = []
    for index in range(width):
        header = raw_headers[index]
        header_text = str(header).strip() if header not in {None, ""} else ""
        if not header_text:
            header_text = f"column_{index + 1}"

        occurrence = seen.get(header_text, 0) + 1
        seen[header_text] = occurrence
        if occurrence > 1:
            header_text = f"{header_text}_{occurrence}"
        normalized.append(header_text)
    return normalized


def to_row_dicts(headers, raw_rows):
    width = max([len(headers), *(len(row) for row in raw_rows)] if raw_rows else [len(headers)])
    normalized_headers = normalize_headers(headers, width=width)

    rows = []
    for raw_row in raw_rows:
        padded_row = list(raw_row) + [None] * (width - len(raw_row))
        rows.append(
            {
                normalized_headers[index]: padded_row[index]
                for index in range(width)
            }
        )
    return normalized_headers, rows


def load_delimited_rows(dataset_file, delimiter):
    dataset_file.file.open("rb")
    try:
        text_stream = io.TextIOWrapper(dataset_file.file, encoding="utf-8-sig", newline="")
        try:
            return [row for row in csv.reader(text_stream, delimiter=delimiter)]
        finally:
            text_stream.detach()
    finally:
        dataset_file.file.close()


def _xlsx_column_to_index(cell_reference):
    letters = "".join(character for character in cell_reference if character.isalpha())
    index = 0
    for character in letters:
        index = (index * 26) + (ord(character.upper()) - ord("A") + 1)
    return max(index - 1, 0)


def _xlsx_text_from_node(node):
    return "".join(
        text_node.text or ""
        for text_node in node.findall(f".//{{{XLSX_MAIN_NS}}}t")
    )


def _load_xlsx_shared_strings(archive):
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [_xlsx_text_from_node(item) for item in root.findall(f"{{{XLSX_MAIN_NS}}}si")]


def _resolve_first_xlsx_sheet_path(archive):
    workbook_root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    first_sheet = workbook_root.find(f".//{{{XLSX_MAIN_NS}}}sheet")
    if first_sheet is None:
        raise ValidationError({"file": ["Workbook does not contain any sheets."]})

    relationship_id = first_sheet.attrib.get(f"{{{XLSX_REL_NS}}}id")
    if not relationship_id:
        raise ValidationError({"file": ["Workbook sheet relationship could not be resolved."]})

    relationships_root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for relationship in relationships_root.findall(f"{{{XLSX_PACKAGE_REL_NS}}}Relationship"):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib["Target"].lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"

    raise ValidationError({"file": ["Workbook sheet relationship could not be resolved."]})


def _coerce_xlsx_value(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline_string = cell.find(f"{{{XLSX_MAIN_NS}}}is")
        return _xlsx_text_from_node(inline_string) if inline_string is not None else ""

    value_node = cell.find(f"{{{XLSX_MAIN_NS}}}v")
    if value_node is None:
        return None

    raw_value = value_node.text or ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw_value)]
        except (IndexError, ValueError):
            return raw_value
    if cell_type == "b":
        return raw_value == "1"
    if cell_type == "str":
        return raw_value

    try:
        numeric_value = float(raw_value)
    except ValueError:
        return raw_value

    return int(numeric_value) if numeric_value.is_integer() else numeric_value


def load_xlsx_rows(dataset_file):
    dataset_file.file.open("rb")
    try:
        with zipfile.ZipFile(dataset_file.file, "r") as archive:
            shared_strings = _load_xlsx_shared_strings(archive)
            sheet_path = _resolve_first_xlsx_sheet_path(archive)
            sheet_root = ElementTree.fromstring(archive.read(sheet_path))

            rows = []
            for row_node in sheet_root.findall(f".//{{{XLSX_MAIN_NS}}}sheetData/{{{XLSX_MAIN_NS}}}row"):
                values = []
                current_index = 0
                for cell_node in row_node.findall(f"{{{XLSX_MAIN_NS}}}c"):
                    cell_index = _xlsx_column_to_index(cell_node.attrib.get("r", "A1"))
                    while current_index < cell_index:
                        values.append(None)
                        current_index += 1
                    values.append(_coerce_xlsx_value(cell_node, shared_strings))
                    current_index += 1
                rows.append(values)
            return rows
    except zipfile.BadZipFile as exc:
        raise ValidationError({"file": ["Invalid XLSX file."]}) from exc
    finally:
        dataset_file.file.close()


def _coerce_xls_value(cell, workbook):
    if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
        return None
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        numeric_value = float(cell.value)
        return int(numeric_value) if numeric_value.is_integer() else numeric_value
    if cell.ctype == xlrd.XL_CELL_DATE:
        year, month, day, hour, minute, second = xlrd.xldate_as_tuple(
            cell.value,
            workbook.datemode,
        )
        if hour == minute == second == 0:
            return f"{year:04d}-{month:02d}-{day:02d}"
        return (
            f"{year:04d}-{month:02d}-{day:02d}"
            f"T{hour:02d}:{minute:02d}:{second:02d}"
        )
    return cell.value


def load_xls_rows(dataset_file):
    dataset_file.file.open("rb")
    try:
        workbook = xlrd.open_workbook(file_contents=dataset_file.file.read())
        if workbook.nsheets == 0:
            raise ValidationError({"file": ["Workbook does not contain any sheets."]})

        sheet = workbook.sheet_by_index(0)
        rows = []
        for row_index in range(sheet.nrows):
            rows.append(
                [
                    _coerce_xls_value(sheet.cell(row_index, column_index), workbook)
                    for column_index in range(sheet.ncols)
                ]
            )
        return rows
    except (xlrd.XLRDError, ValueError) as exc:
        raise ValidationError({"file": ["Invalid XLS file."]}) from exc
    finally:
        dataset_file.file.close()


def load_json_payload(dataset_file):
    dataset_file.file.open("rb")
    try:
        text_stream = io.TextIOWrapper(dataset_file.file, encoding="utf-8-sig")
        try:
            return json.load(text_stream)
        except json.JSONDecodeError as exc:
            raise ValidationError({"file": ["Invalid JSON file."]}) from exc
        finally:
            text_stream.detach()
    finally:
        dataset_file.file.close()


def load_xml_root(dataset_file):
    dataset_file.file.open("rb")
    try:
        try:
            return ElementTree.fromstring(dataset_file.file.read())
        except ElementTree.ParseError as exc:
            raise ValidationError({"file": ["Invalid XML file."]}) from exc
    finally:
        dataset_file.file.close()


def local_name(tag):
    return tag.split("}", 1)[-1]


def is_sdmx_json_payload(payload):
    return bool(
        isinstance(payload, dict)
        and (
            ("structure" in payload and "dataSets" in payload)
            or (
                isinstance(payload.get("meta"), dict)
                and "sdmx" in json.dumps(payload["meta"]).lower()
            )
        )
    )


def is_sdmx_xml_root(root):
    return "sdmx" in root.tag.lower()


def build_json_rows(payload):
    rows_source = payload
    if isinstance(payload, dict):
        rows_source = payload["data"] if isinstance(payload.get("data"), list) else [payload]
    elif not isinstance(payload, list):
        rows_source = [payload]

    if not rows_source:
        return [], []

    if all(isinstance(item, dict) for item in rows_source):
        headers = []
        for item in rows_source:
            for key in item.keys():
                key = str(key)
                if key not in headers:
                    headers.append(key)
        rows = [{header: item.get(header) for header in headers} for item in rows_source]
        return headers, rows

    if all(isinstance(item, (list, tuple)) for item in rows_source):
        max_width = max(len(item) for item in rows_source)
        headers = normalize_headers([], width=max_width)
        rows = [
            {
                headers[index]: (list(item) + [None] * (max_width - len(item)))[index]
                for index in range(max_width)
            }
            for item in rows_source
        ]
        return headers, rows

    return ["value"], [{"value": item} for item in rows_source]


def paginate_items(items, offset, limit):
    total_items = len(items)
    sliced_items = items[offset:] if limit is None else items[offset: offset + limit]
    return {
        "offset": offset,
        "limit": total_items - offset if limit is None else limit,
        "returned_items": len(sliced_items),
        "total_items": total_items,
        "returned_rows": len(sliced_items),
        "total_rows": total_items,
        "has_more": offset + len(sliced_items) < total_items,
    }


def build_tabular_payload(dataset_file, raw_rows, offset, limit, *, structure_type="tabular", data=None):
    if raw_rows:
        columns, rows = to_row_dicts(raw_rows[0], raw_rows[1:])
    else:
        columns, rows = [], []
    page = paginate_items(rows, offset, limit)
    return {
        "structure_type": structure_type,
        "columns": columns,
        "rows": rows[offset:] if limit is None else rows[offset: offset + limit],
        "data": data,
        "warnings": [],
        **page,
    }


def _sdmx_dimension_value_map(definitions, key):
    indexes = [part for part in (key or "").split(":") if part != ""]
    resolved = {}
    for index, definition in enumerate(definitions):
        dimension_id = definition.get("id") or f"dimension_{index + 1}"
        values = definition.get("values") or []
        try:
            value_index = int(indexes[index])
        except (IndexError, ValueError):
            resolved[dimension_id] = None
            continue

        if 0 <= value_index < len(values):
            value_definition = values[value_index]
            resolved[dimension_id] = (
                value_definition.get("id")
                or value_definition.get("name")
                or value_index
            )
        else:
            resolved[dimension_id] = None
    return resolved


def _sdmx_measure_value(raw_value):
    if isinstance(raw_value, list):
        return raw_value[0] if raw_value else None
    if isinstance(raw_value, dict):
        if "0" in raw_value:
            return raw_value["0"]
        if "value" in raw_value:
            return raw_value["value"]
        first_key = next(iter(raw_value), None)
        return raw_value[first_key] if first_key is not None else None
    return raw_value


def parse_sdmx_json_payload(payload):
    structure = payload.get("structure") or {}
    dimensions = structure.get("dimensions") or {}
    observation_dimensions = dimensions.get("observation") or []
    series_dimensions = dimensions.get("series") or []
    observation_attributes = ((structure.get("attributes") or {}).get("observation") or [])
    observation_measures = ((structure.get("measures") or {}).get("observation") or [])
    dataset_payload = payload.get("dataSets") or []
    dataset_payload = dataset_payload[0] if dataset_payload else {}

    observations = []
    if isinstance(dataset_payload.get("series"), dict):
        for series_key, series_value in dataset_payload["series"].items():
            series_context = _sdmx_dimension_value_map(series_dimensions, series_key)
            for obs_key, obs_value in (series_value.get("observations") or {}).items():
                record = {
                    **series_context,
                    **_sdmx_dimension_value_map(observation_dimensions, obs_key),
                    "value": _sdmx_measure_value(obs_value),
                }
                observations.append(record)
    else:
        for obs_key, obs_value in (dataset_payload.get("observations") or {}).items():
            record = {
                **_sdmx_dimension_value_map(observation_dimensions, obs_key),
                "value": _sdmx_measure_value(obs_value),
            }
            observations.append(record)

    columns = []
    for observation in observations:
        for key in observation.keys():
            if key not in columns:
                columns.append(key)

    return {
        "format": "json",
        "dimensions": [definition.get("id") for definition in (series_dimensions + observation_dimensions)],
        "measures": [definition.get("id") for definition in observation_measures] or ["value"],
        "attributes": [definition.get("id") for definition in observation_attributes],
        "metadata": payload.get("header") or {},
        "columns": columns,
        "observations": observations,
    }


def _extract_sdmx_value_pairs(node):
    result = {}
    for value_node in node.findall(".//*"):
        if local_name(value_node.tag) == "Value" and "id" in value_node.attrib:
            result[value_node.attrib["id"]] = value_node.attrib.get("value")
    return result


def _extract_xml_observation_record(observation_node, series_context=None):
    record = dict(series_context or {})
    record.update(observation_node.attrib)
    for child in observation_node:
        child_name = local_name(child.tag)
        if child_name in {"ObsDimension", "Time"} and "value" in child.attrib:
            record[child.attrib.get("id", child_name)] = child.attrib["value"]
        elif child_name == "ObsValue":
            record["value"] = child.attrib.get("value")
        elif child_name in {"ObsKey", "Attributes"}:
            record.update(_extract_sdmx_value_pairs(child))
        elif child_name == "Value" and "id" in child.attrib:
            record[child.attrib["id"]] = child.attrib.get("value")

    if "OBS_VALUE" in record and "value" not in record:
        record["value"] = record["OBS_VALUE"]
    return record


def parse_sdmx_xml_payload(root):
    observations = []
    metadata = {"root": local_name(root.tag)}

    series_nodes = [node for node in root.iter() if local_name(node.tag) == "Series"]
    for series_node in series_nodes:
        series_context = {}
        for child in series_node:
            child_name = local_name(child.tag)
            if child_name in {"SeriesKey", "Attributes"}:
                series_context.update(_extract_sdmx_value_pairs(child))

        for child in series_node:
            if local_name(child.tag) == "Obs":
                observations.append(_extract_xml_observation_record(child, series_context))

    if not observations:
        for observation_node in [node for node in root.iter() if local_name(node.tag) == "Obs"]:
            observations.append(_extract_xml_observation_record(observation_node))

    if not observations:
        raise ValidationError({"file": ["No SDMX observations could be extracted from the XML file."]})

    columns = []
    for observation in observations:
        for key in observation.keys():
            if key not in columns:
                columns.append(key)

    return {
        "format": "xml",
        "dimensions": [column for column in columns if column != "value"],
        "measures": ["value"],
        "attributes": [],
        "metadata": metadata,
        "columns": columns,
        "observations": observations,
    }


def build_sdmx_payload(dataset_file, parsed_payload, offset, limit):
    observations = parsed_payload["observations"]
    page = paginate_items(observations, offset, limit)
    return {
        "structure_type": "sdmx",
        "columns": parsed_payload["columns"],
        "rows": observations[offset:] if limit is None else observations[offset: offset + limit],
        "sdmx": {
            "format": parsed_payload["format"],
            "dimensions": parsed_payload["dimensions"],
            "measures": parsed_payload["measures"],
            "attributes": parsed_payload["attributes"],
            "metadata": parsed_payload["metadata"],
        },
        "warnings": [],
        **page,
    }


def build_pdf_payload(dataset_file, offset, limit):
    dataset_file.file.open("rb")
    try:
        reader = PdfReader(dataset_file.file)
        total_pages = len(reader.pages)
        end_index = total_pages if limit is None else min(total_pages, offset + limit)
        pages = []
        warnings = []
        for page_index in range(offset, end_index):
            text = reader.pages[page_index].extract_text() or ""
            if not text.strip():
                warnings.append(f"No extractable text found on page {page_index + 1}.")
            pages.append(
                {
                    "page_number": page_index + 1,
                    "text": text,
                }
            )

        page = paginate_items(list(range(total_pages)), offset, limit)
        return {
            "structure_type": "document",
            "document": {
                "page_count": total_pages,
                "pages": pages,
                "text_excerpt": "\n".join(page_data["text"] for page_data in pages).strip()[:2000],
            },
            "warnings": warnings,
            **page,
        }
    finally:
        dataset_file.file.close()


def build_json_payload(dataset_file, payload, offset, limit):
    columns, rows = build_json_rows(payload)
    page = paginate_items(rows, offset, limit)
    sliced_rows = rows[offset:] if limit is None else rows[offset: offset + limit]
    return {
        "structure_type": "json",
        "columns": columns,
        "rows": sliced_rows,
        "data": sliced_rows,
        "warnings": [],
        **page,
    }


def build_structured_payload(dataset_file, offset, limit):
    file_format = (dataset_file.file_format or "").lower()

    if file_format not in STRUCTURED_DATA_SUPPORTED_FORMATS:
        raise ValidationError(
            {
                "file_format": [
                    "Structured API access is supported only for csv, tsv, json, xls, xlsx, sdmx/xml, and pdf files."
                ]
            }
        )

    if file_format == "csv":
        return build_tabular_payload(dataset_file, load_delimited_rows(dataset_file, ","), offset, limit)

    if file_format == "tsv":
        return build_tabular_payload(dataset_file, load_delimited_rows(dataset_file, "\t"), offset, limit)

    if file_format == "xlsx":
        return build_tabular_payload(dataset_file, load_xlsx_rows(dataset_file), offset, limit)

    if file_format == "xls":
        return build_tabular_payload(dataset_file, load_xls_rows(dataset_file), offset, limit)

    if file_format == "pdf":
        return build_pdf_payload(dataset_file, offset, limit)

    if file_format == "json":
        payload = load_json_payload(dataset_file)
        if is_sdmx_json_payload(payload):
            return build_sdmx_payload(dataset_file, parse_sdmx_json_payload(payload), offset, limit)
        return build_json_payload(dataset_file, payload, offset, limit)

    root = load_xml_root(dataset_file)
    if not is_sdmx_xml_root(root):
        raise ValidationError({"file": ["Only SDMX XML files are supported for structured XML access."]})
    return build_sdmx_payload(dataset_file, parse_sdmx_xml_payload(root), offset, limit)
