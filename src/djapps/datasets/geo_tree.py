def region_code_from_council(area_code: str) -> str:
    code = str(area_code or "").strip()
    if len(code) >= 3 and code[0] in {"1", "2"}:
        try:
            return str(int(code[1:3]))
        except ValueError:
            return ""
    return ""


def canonical_geo_parent(area_level: str, area_code: str, parent_code: str) -> str:
    """Parent area_code at the previous census grain (not TISP D-keys)."""
    level = str(area_level or "").strip().upper()
    parent = str(parent_code or "").strip()
    if parent.startswith("D") and parent[1:].isdigit():
        parent = parent[1:]
    if level == "LVL5":
        return region_code_from_council(area_code) or parent
    return parent


def row_geo_parent(row: dict) -> str:
    geo_parent = str(row.get("geo_parent_code") or "").strip()
    if geo_parent:
        return geo_parent
    return canonical_geo_parent(
        str(row.get("area_level") or ""),
        str(row.get("area_code") or ""),
        str(row.get("parent_code") or ""),
    )


def parse_area_levels(raw_value):
    if not raw_value:
        return None
    levels = [part.strip() for part in str(raw_value).split(",") if part.strip()]
    return set(levels) or None


def filter_geo_rows(rows, *, area_levels=None, parent_code=None, area_code_prefix=None):
    if not area_levels and not parent_code and not area_code_prefix:
        return rows

    filtered = []
    for row in rows:
        if area_levels and str(row.get("area_level") or "") not in area_levels:
            continue
        if parent_code and row_geo_parent(row) != parent_code:
            continue
        if area_code_prefix and not str(row.get("area_code") or "").startswith(
            area_code_prefix
        ):
            continue
        filtered.append(row)
    return filtered
