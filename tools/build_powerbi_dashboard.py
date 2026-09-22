"""Build the two Power BI report pages from documented enhanced-PBIR templates.

This utility changes report-definition JSON only.  It deliberately does not
touch the semantic model, CSV exports, Parquet files, or source analysis.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "powerbi" / "Chess Analytics.Report" / "definition"
PAGES = REPORT / "pages"
VISUAL_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "visualContainer/2.12.0/schema.json"
)
PAGE_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "page/2.1.0/schema.json"
)

NAVY = "#071A33"
PANEL = "#0E2B50"
PANEL_ALT = "#12385F"
LIGHT = "#F4F7FB"
MUTED = "#B9C8D8"
ORANGE = "#FF9F1C"
CYAN = "#31C3D9"
BORDER = "#1D496F"

UPSET_PAGE = "a5e20ca28bc3bb0a7a06"
OPENING_PAGE = "b4d8a1f2c6e793045b1a"


def literal(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def color(value: str) -> dict:
    return {"solid": {"color": literal(f"'{value}'")}}


def source_ref(table: str) -> dict:
    return {"SourceRef": {"Entity": table}}


def column(table: str, name: str) -> dict:
    return {"Column": {"Expression": source_ref(table), "Property": name}}


def measure(table: str, name: str) -> dict:
    return {"Measure": {"Expression": source_ref(table), "Property": name}}


def projection(field: dict, query_ref: str, native_ref: str) -> dict:
    return {"field": field, "queryRef": query_ref, "nativeQueryRef": native_ref}


def position(x: int, y: int, width: int, height: int, tab_order: int) -> dict:
    return {
        "x": x,
        "y": y,
        "z": tab_order,
        "width": width,
        "height": height,
        "tabOrder": tab_order,
    }


def padding(value: str = "8D") -> list[dict]:
    return [{"properties": {side: literal(value) for side in ("top", "bottom", "left", "right")}}]


def container_style(title: str | None = None) -> dict:
    style = {
        "background": [{"properties": {"show": literal("true"), "color": color(PANEL), "transparency": literal("0D")}}],
        "border": [{"properties": {"show": literal("true"), "color": color(BORDER), "width": literal("1D"), "radius": literal("8D")}}],
        "padding": padding(),
    }
    if title:
        style["title"] = [{"properties": {"text": literal(f"'{title}'"), "fontColor": color(LIGHT), "background": color(PANEL), "alignment": literal("'left'")}}]
    return style


def visual(name: str, x: int, y: int, width: int, height: int, tab_order: int, visual_type: str, body: dict) -> dict:
    return {
        "$schema": VISUAL_SCHEMA,
        "name": name,
        "position": position(x, y, width, height, tab_order),
        "visual": {"visualType": visual_type, **body},
    }


def textbox(name: str, x: int, y: int, width: int, height: int, tab_order: int, text: str, font_size: str, font_color: str = LIGHT) -> dict:
    return visual(name, x, y, width, height, tab_order, "textbox", {
        "objects": {
            "general": [{"properties": {"paragraphs": [{"textRuns": [{"value": text, "textStyle": {"fontFamily": "Segoe UI Semibold", "fontSize": font_size, "color": font_color}}], "horizontalTextAlignment": "left"}]}}]
        },
        "visualContainerObjects": {
            "background": [{"properties": {"show": literal("false")}}],
            "border": [{"properties": {"show": literal("false")}}],
            "padding": padding("0D"),
        },
    })


def card(name: str, x: int, y: int, width: int, height: int, tab_order: int, table: str, measure_name: str, label: str, accent: str) -> dict:
    query_ref = f"{table}.{measure_name}"
    return visual(name, x, y, width, height, tab_order, "cardVisual", {
        "query": {"queryState": {"Data": {"projections": [projection(measure(table, measure_name), query_ref, measure_name)]}}},
        "objects": {
            "label": [{"properties": {"show": literal("true"), "text": literal(f"'{label}'"), "fontColor": color(MUTED)}, "selector": {"id": "default"}}],
            "value": [{"properties": {"fontColor": color(LIGHT), "fontSize": literal("28D"), "bold": literal("true")}, "selector": {"id": "default"}}],
            "outline": [{"properties": {"show": literal("false")}, "selector": {"id": "default"}}],
            "accentBar": [{"properties": {"show": literal("true"), "color": color(accent)}, "selector": {"id": "default"}}],
        },
        "visualContainerObjects": container_style(),
    })


def slicer(name: str, x: int, y: int, width: int, tab_order: int, table: str, field_name: str, label: str) -> dict:
    return visual(name, x, y, width, 80, tab_order, "slicer", {
        "query": {"queryState": {"Values": {"projections": [projection(column(table, field_name), f"{table}.{field_name}", field_name)]}}},
        "objects": {
            "data": [{"properties": {"mode": literal("'Dropdown'")}}],
            "header": [{"properties": {"show": literal("true"), "text": literal(f"'{label}'")}}],
        },
        "visualContainerObjects": container_style(),
    })


def chart(name: str, x: int, y: int, width: int, height: int, tab_order: int, table: str, category: str, measure_name: str, title: str) -> dict:
    query_ref = f"{table}.{measure_name}"
    return visual(name, x, y, width, height, tab_order, "clusteredColumnChart", {
        "query": {
            "queryState": {
                "Category": {"projections": [projection(column(table, category), f"{table}.{category}", category)]},
                "Y": {"projections": [projection(measure(table, measure_name), query_ref, measure_name)]},
            },
            "sortDefinition": {"sort": [{"field": measure(table, measure_name), "direction": "Descending"}], "isDefaultSort": False},
        },
        "objects": {
            "dataPoint": [{"properties": {"fill": color(CYAN)}, "selector": {"metadata": query_ref}}],
            "labels": [{"properties": {"show": literal("true")}}],
            "categoryAxis": [{"properties": {"labelColor": color(LIGHT), "titleColor": color(LIGHT)}}],
            "valueAxis": [{"properties": {"labelColor": color(LIGHT), "titleColor": color(LIGHT), "start": literal("0D")}}],
        },
        "visualContainerObjects": container_style(title),
    })


def outcome_chart(name: str, x: int, y: int, width: int, height: int, tab_order: int) -> dict:
    table = "OpeningPerformance"
    measures = ["Opening Wins", "Opening Draws", "Opening Losses"]
    colors = [ORANGE, CYAN, "#8BA6C1"]
    projections = [projection(measure(table, item), f"{table}.{item}", item) for item in measures]
    points = [{"properties": {"fill": color(shade)}, "selector": {"metadata": f"{table}.{item}"}} for item, shade in zip(measures, colors)]
    return visual(name, x, y, width, height, tab_order, "clusteredColumnChart", {
        "query": {"queryState": {"Category": {"projections": [projection(column(table, "player_color"), f"{table}.player_color", "player_color")]}, "Y": {"projections": projections}}},
        "objects": {
            "dataPoint": points,
            "labels": [{"properties": {"show": literal("true")}}],
            "legend": [{"properties": {"position": literal("'TopCenter'")}}],
            "categoryAxis": [{"properties": {"labelColor": color(LIGHT), "titleColor": color(LIGHT)}}],
            "valueAxis": [{"properties": {"labelColor": color(LIGHT), "titleColor": color(LIGHT), "start": literal("0D")}}],
        },
        "visualContainerObjects": container_style("Observed outcomes by player color"),
    })


def qualified_opening_filter() -> dict:
    """Visual-level dynamic filter: each opening/group must have 100+ sides."""
    return {
        "name": "FilterOpeningSampleEligible100",
        "field": measure("OpeningPerformance", "Opening Sample Eligible"),
        "type": "Advanced",
        "filter": {
            "Version": 2,
            "From": [{"Name": "o", "Entity": "OpeningPerformance", "Type": 0}],
            "Where": [{"Condition": {"Comparison": {
                "ComparisonKind": 0,
                "Left": {"Measure": {"Expression": {"SourceRef": {"Source": "o"}}, "Property": "Opening Sample Eligible"}},
                "Right": {"Literal": {"Value": "1L"}},
            }}}],
        },
        "howCreated": "User",
    }


def opening_table(name: str, x: int, y: int, width: int, height: int, tab_order: int) -> dict:
    table = "OpeningPerformance"
    cols = ["opening_name", "eco_code", "rating_band", "player_color", "speed_category"]
    measures = ["Player-Side Games", "Opening Win Rate", "Opening Draw Rate", "Opening Loss Rate"]
    values = [projection(column(table, col), f"{table}.{col}", col) for col in cols]
    values += [projection(measure(table, item), f"{table}.{item}", item) for item in measures]
    result = visual(name, x, y, width, height, tab_order, "tableEx", {
        "query": {"queryState": {"Values": {"projections": values}}, "sortDefinition": {"sort": [{"field": measure(table, "Player-Side Games"), "direction": "Descending"}], "isDefaultSort": False}},
        "objects": {
            "columnHeaders": [{"properties": {"fontColor": color(LIGHT), "backColor": color(PANEL_ALT), "autoSizeColumnWidth": literal("true"), "columnAdjustment": literal("'growToFit'")}}],
            "values": [{"properties": {"fontColorPrimary": color(LIGHT), "fontColorSecondary": color(LIGHT), "backColorPrimary": color(PANEL), "backColorSecondary": color("#0B2442")}}],
        },
        "visualContainerObjects": {**container_style("Openings meeting the 100 player-side-game requirement"), "stylePreset": [{"properties": {"name": literal("'None'")}}]},
    })
    # filterConfig belongs to the visual container, not visual.configuration.
    result["filterConfig"] = {"filters": [qualified_opening_filter()]}
    return result


def page_definition(name: str, display_name: str) -> dict:
    return {
        "$schema": PAGE_SCHEMA,
        "name": name,
        "displayName": display_name,
        "displayOption": "FitToPage",
        "height": 1080,
        "width": 1920,
        "objects": {
            "background": [{"properties": {"color": color(NAVY), "transparency": literal("0D")}}],
            "outspace": [{"properties": {"color": color(NAVY), "transparency": literal("0D")}}],
        },
    }


def write_visuals(page: str, visuals: list[dict]) -> None:
    visual_root = PAGES / page / "visuals"
    visual_root.mkdir(parents=True, exist_ok=True)
    for item in visuals:
        target = visual_root / item["name"]
        target.mkdir(exist_ok=True)
        (target / "visual.json").write_text(json.dumps(item, indent=2) + "\n", encoding="utf-8")


def build() -> None:
    # Page 1: Rating Upsets.
    (PAGES / UPSET_PAGE).mkdir(parents=True, exist_ok=True)
    (PAGES / UPSET_PAGE / "page.json").write_text(json.dumps(page_definition(UPSET_PAGE, "Rating Upsets"), indent=2) + "\n", encoding="utf-8")
    upset = "RatingUpsets"
    upset_visuals = [
        textbox("10000000000000000001", 56, 32, 880, 52, 1, "Chess Analytics | Rating Upsets", "30px"),
        textbox("10000000000000000002", 56, 88, 1100, 32, 2, "500,000-game sample from the beginning of August 2026", "15px", MUTED),
        card("10000000000000000003", 56, 152, 360, 144, 3, upset, "Eligible Games", "Eligible Games", CYAN),
        card("10000000000000000004", 440, 152, 360, 144, 4, upset, "Upset Games", "Upset Games", ORANGE),
        card("10000000000000000005", 824, 152, 360, 144, 5, upset, "Upset Rate", "Observed Upset Rate", ORANGE),
        slicer("10000000000000000006", 1224, 152, 200, 6, upset, "speed_category", "Speed category"),
        slicer("10000000000000000007", 1448, 152, 200, 7, upset, "rating_gap_band", "Rating-gap band"),
        slicer("10000000000000000008", 1672, 152, 200, 8, upset, "lower_rated_player_band", "Lower-rated band"),
        chart("10000000000000000009", 56, 336, 576, 352, 9, upset, "rating_gap_band", "Upset Rate", "Observed upset rate by rating-gap band"),
        chart("10000000000000000010", 664, 336, 576, 352, 10, upset, "speed_category", "Upset Rate", "Observed upset rate by speed category"),
        chart("10000000000000000011", 1272, 336, 600, 352, 11, upset, "lower_rated_player_band", "Upset Rate", "Observed upset rate by lower-rated player band"),
        textbox("10000000000000000012", 56, 736, 1816, 120, 12, "Methodology: an upset is a win by the lower-rated player against an opponent rated at least 100 Elo higher. Draws remain in the eligible-game denominator. Rates are descriptive of this early-August sample, not all Lichess games.", "17px", MUTED),
    ]
    write_visuals(UPSET_PAGE, upset_visuals)

    # Page 2: Opening Performance Explorer.
    (PAGES / OPENING_PAGE).mkdir(parents=True, exist_ok=True)
    (PAGES / OPENING_PAGE / "page.json").write_text(json.dumps(page_definition(OPENING_PAGE, "Opening Performance Explorer"), indent=2) + "\n", encoding="utf-8")
    opening = "OpeningPerformance"
    opening_visuals = [
        textbox("20000000000000000001", 56, 32, 950, 52, 1, "Chess Analytics | Opening Performance Explorer", "30px"),
        textbox("20000000000000000002", 56, 88, 1300, 32, 2, "Player-side observations from comparable opponents in the beginning-of-August 2026 sample", "15px", MUTED),
        slicer("20000000000000000003", 56, 144, 440, 3, opening, "opening_name", "Opening selector"),
        slicer("20000000000000000004", 520, 144, 280, 4, opening, "rating_band", "Rating band"),
        slicer("20000000000000000005", 824, 144, 240, 5, opening, "player_color", "Player color"),
        slicer("20000000000000000006", 1088, 144, 260, 6, opening, "speed_category", "Speed category"),
        card("20000000000000000007", 56, 256, 336, 128, 7, opening, "Player-Side Games", "Player-Side Games", CYAN),
        card("20000000000000000008", 416, 256, 336, 128, 8, opening, "Opening Wins", "Opening Wins", ORANGE),
        card("20000000000000000009", 776, 256, 336, 128, 9, opening, "Opening Draws", "Opening Draws", CYAN),
        card("20000000000000000010", 1136, 256, 336, 128, 10, opening, "Opening Losses", "Opening Losses", "#8BA6C1"),
        card("20000000000000000011", 1496, 256, 376, 128, 11, opening, "Opening Win Rate", "Observed Win Rate", ORANGE),
        outcome_chart("20000000000000000012", 56, 424, 624, 336, 12),
        opening_table("20000000000000000013", 712, 424, 1160, 440, 13),
        textbox("20000000000000000014", 56, 904, 1816, 88, 14, "Comparison rule: the table applies the 100 player-side-game minimum separately to every opening, rating band, player color and speed-category combination. These are player-side observations, not unique games; the 764,194 total is not a game count. Opening outcomes are descriptive associations, not causal effects.", "16px", MUTED),
    ]
    write_visuals(OPENING_PAGE, opening_visuals)

    pages_metadata = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [UPSET_PAGE, OPENING_PAGE],
        "activePageName": UPSET_PAGE,
    }
    (PAGES / "pages.json").write_text(json.dumps(pages_metadata, indent=2) + "\n", encoding="utf-8")


def validate() -> None:
    """Validate JSON and the report/model field references used by these pages."""
    expected = {
        "RatingUpsets": {
            "columns": {"speed_category", "rating_gap_band", "lower_rated_player_band"},
            "measures": {"Eligible Games", "Upset Games", "Upset Rate"},
        },
        "OpeningPerformance": {
            "columns": {"opening_name", "eco_code", "rating_band", "player_color", "speed_category"},
            "measures": {"Player-Side Games", "Opening Wins", "Opening Draws", "Opening Losses", "Opening Win Rate", "Opening Draw Rate", "Opening Loss Rate", "Opening Sample Eligible"},
        },
    }
    problems: list[str] = []
    json_files = list(REPORT.rglob("*.json"))
    for item in json_files:
        try:
            json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"Invalid JSON: {item}: {error}")

    pages = json.loads((PAGES / "pages.json").read_text(encoding="utf-8"))
    if pages["pageOrder"] != [UPSET_PAGE, OPENING_PAGE]:
        problems.append("pages.json does not contain the expected two-page order")
    for page in pages["pageOrder"]:
        if not (PAGES / page / "page.json").is_file():
            problems.append(f"Missing page definition: {page}")

    def references(node: object) -> list[tuple[str, str, str]]:
        found: list[tuple[str, str, str]] = []
        if isinstance(node, dict):
            for kind in ("Column", "Measure"):
                expression = node.get(kind)
                if isinstance(expression, dict):
                    source = expression.get("Expression", {}).get("SourceRef", {})
                    table = source.get("Entity")
                    field = expression.get("Property")
                    if isinstance(table, str) and isinstance(field, str):
                        found.append((kind, table, field))
            for value in node.values():
                found.extend(references(value))
        elif isinstance(node, list):
            for value in node:
                found.extend(references(value))
        return found

    for item in REPORT.glob("pages/*/visuals/*/visual.json"):
        data = json.loads(item.read_text(encoding="utf-8"))
        if not re.fullmatch(r"[0-9a-f]{20}", data.get("name", "")):
            problems.append(f"Invalid 20-hex visual name: {item}")
        if data.get("name") != item.parent.name:
            problems.append(f"Visual folder/name mismatch: {item}")
        for kind, table, field in references(data):
            if table not in expected or field not in expected[table]["columns" if kind == "Column" else "measures"]:
                problems.append(f"Unresolvable {kind} reference {table}[{field}] in {item}")
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"Validated {len(json_files)} JSON files and {len(list(REPORT.glob('pages/*/visuals/*/visual.json')))} visuals.")


if __name__ == "__main__":
    if "--validate" in sys.argv:
        validate()
    else:
        build()
