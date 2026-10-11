"""MAPPING AGENT (BOQ -> BOM).

1. MATCH each BOQ line to a work item in data/recipes.csv using
   TF-IDF cosine similarity on the description (same unit only).
2. CONVERT work quantity -> material quantity using recipe consumption rates.
3. PRICE using data/material_catalog.csv.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from constructai.boq.schemas import BOQ


DATA = Path(__file__).resolve().parents[3] / "data"

STOP = {
    "of", "to", "under", "for", "up", "the",
    "and", "over", "with", "at", "in", "on"
}

COUNTABLE = {"bag", "nos", "sheet"}

OK_SCORE = 0.75
REVIEW_SCORE = 0.35


@dataclass
class BOMResult:
    lines: list = field(default_factory=list)
    mapping: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    total_cost: float = 0.0
    by_category: list = field(default_factory=list)


def _tokens(text: str):
    text = text.lower()

    text = re.sub(
        r"\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*m\b",
        " ",
        text,
    )

    text = re.sub(r"(\d+)\s*mm", r"\1mm", text)

    return [
        word
        for word in re.findall(r"\d+mm|[a-z]+", text)
        if word not in STOP and len(word) > 1
    ]


class MappingAgent:

    def __init__(self, catalog_path=None, recipes_path=None):

        catalog_path = catalog_path or DATA / "material_catalog.csv"
        recipes_path = recipes_path or DATA / "recipes.csv"

        self.catalog = {}

        with open(
            catalog_path,
            newline="",
            encoding="utf-8",
        ) as f:
            for row in csv.DictReader(f):
                self.catalog[row["material_id"]] = {
                    **row,
                    "rate_inr": float(row["rate_inr"]),
                    "wastage_pct": float(row["wastage_pct"]),
                }

        self.works = {}

        with open(
            recipes_path,
            newline="",
            encoding="utf-8",
        ) as f:
            reader = csv.DictReader(f)
            if "requires_thickness" not in (reader.fieldnames or []):
                raise ValueError("Recipe catalog is missing the requires_thickness column")
            for row_number, row in enumerate(reader, start=2):
                thickness_flag = row["requires_thickness"].strip().lower()
                if thickness_flag not in {"", "true", "false"}:
                    raise ValueError(
                        f"Recipe catalog row {row_number} has invalid requires_thickness value"
                    )

                work = self.works.setdefault(
                    row["work_key"],
                    {
                        "text": row["match_text"],
                        "unit": row["unit"],
                        "requires_thickness": thickness_flag == "true",
                        "rows": [],
                    },
                )

                work["rows"].append(
                    (
                        row["material_id"],
                        float(row["qty_per_unit"]),
                        row["note"],
                    )
                )

        n = len(self.works)

        df = Counter(
            token
            for work in self.works.values()
            for token in set(_tokens(work["text"]))
        )

        self.idf = {
            token: math.log((1 + n) / (1 + count)) + 1
            for token, count in df.items()
        }

    def _vec(self, text: str):

        counter = Counter(_tokens(text))

        vector = {
            token: (1 + math.log(count)) * self.idf.get(token, 1.0)
            for token, count in counter.items()
        }

        norm = math.sqrt(
            sum(value * value for value in vector.values())
        ) or 1.0

        return vector, norm

    def _score(self, a: str, b: str):

        (vector_a, norm_a), (vector_b, norm_b) = (
            self._vec(a),
            self._vec(b),
        )

        return sum(
            value * vector_b.get(token, 0)
            for token, value in vector_a.items()
        ) / (norm_a * norm_b)

    def match(self, description: str, unit: str):

        best = max(
            (
                (
                    self._score(description, work["text"]),
                    key,
                )
                for key, work in self.works.items()
                if work["unit"] == unit
            ),
            default=(0.0, None),
        )

        return best[1], best[0]

    def recipe_options(self, unit: str) -> list[dict[str, str]]:
        return [
            {"work_key": key, "description": work["text"], "unit": work["unit"]}
            for key, work in self.works.items()
            if work["unit"] == unit
        ]

    def run(
        self,
        boq: BOQ,
        manual_mappings: dict[int, str] | None = None,
    ) -> BOMResult:

        out, acc = BOMResult(), {}
        validation_errors = []
        validation_warnings = []
        manual_mappings = manual_mappings or {}

        for it in boq.items:

            description = it.description
            unit = it.unit
            quantity = float(it.quantity)
            item_number = it.item_number

            key, score = self.match(description, unit)
            manually_mapped = item_number in manual_mappings
            if manually_mapped:
                selected_key = manual_mappings[item_number]
                selected_work = self.works.get(selected_key)
                if selected_work is None or selected_work["unit"] != unit:
                    validation_errors.append(
                        f"BOQ {item_number}: selected recipe is invalid for unit '{unit}'."
                    )
                    key, score = None, 0.0
                    manually_mapped = False
                else:
                    key, score = selected_key, 1.0

            status = "MANUAL" if manually_mapped else (
                "OK"
                if score >= OK_SCORE
                else "REVIEW"
                if score >= REVIEW_SCORE
                else "NO MATCH"
            )

            out.mapping.append(
                {
                    "BOQ item": str(item_number),
                    "Description": description,
                    "Matched work item": (
                        f"{self.works[key]['text']} (manual selection)"
                        if key and status == "MANUAL"
                        else self.works[key]["text"]
                        if key and status != "NO MATCH"
                        else "-"
                    ),
                    "Confidence": round(score, 2),
                    "Status": status,
                }
            )

            if status == "NO MATCH":

                validation_errors.append(
                    f"BOQ {item_number} '{description}': "
                    "no work-item recipe match. Correct the BOQ description/unit "
                    "or select a verified recipe in the BOM mapping table."
                )

                continue

            work = self.works[key]
            if status == "REVIEW":
                validation_errors.append(
                    f"BOQ {item_number} matched '{work['text']}' with low confidence "
                    f"({score:.2f}); select and confirm the correct recipe before continuing."
                )
                continue

            mult = 1.0

            if work["requires_thickness"]:
                match = re.search(
                    r"(\d+(?:\.\d+)?)\s*mm",
                    description,
                )

                thickness_mm = float(match.group(1)) if match else None
                if (
                    thickness_mm is None
                    and it.dimensions is not None
                    and it.dimensions.width is not None
                    and it.dimensions_source in {"human", "ocr"}
                ):
                    thickness_mm = float(it.dimensions.width) * 1000

                if thickness_mm is None:
                    validation_errors.append(
                        f"BOQ {item_number} '{description}': the selected recipe requires "
                        "a verified thickness in millimetres. Add the thickness explicitly "
                        "from the reviewed drawing dimensions or BOQ description before generating the BOM."
                    )
                    continue

                mult = thickness_mm / 1000

            for material_id, per, note in work["rows"]:

                if material_id == "NONE":
                    continue

                material = acc.setdefault(
                    material_id,
                    {
                        "net": 0.0,
                        "used": [],
                    },
                )

                material["net"] += (
                    quantity * mult * per
                )

                if str(item_number) not in material["used"]:
                    material["used"].append(
                        str(item_number)
                    )

            if status == "MANUAL":
                validation_warnings.append(
                    f"BOQ {item_number} was manually mapped to '{work['text']}'; "
                    "confirm the recipe matches the actual construction."
                )

        categories = {}

        for material_id, material_data in sorted(
            acc.items(),
            key=lambda kv: (
                self.catalog[kv[0]]["category"],
                kv[0],
            ),
        ):

            material = self.catalog[material_id]

            gross = material_data["net"] * (
                1 + material["wastage_pct"] / 100
            )

            order = (
                math.ceil(round(gross, 6))
                if material["unit"] in COUNTABLE
                else round(gross, 2)
            )

            cost = order * material["rate_inr"]

            out.lines.append(
                {
                    "Material": material["name"],
                    "Category": material["category"],
                    "Unit": material["unit"],
                    "Net qty": round(
                        material_data["net"],
                        2,
                    ),
                    "Wastage %": material["wastage_pct"],
                    "Order qty": order,
                    "Rate (Rs)": material["rate_inr"],
                    "Cost (Rs)": round(cost),
                    "Used in BOQ items": ", ".join(
                        material_data["used"]
                    ),
                }
            )

            categories[material["category"]] = (
                categories.get(material["category"], 0)
                + cost
            )

        out.total_cost = round(
            sum(categories.values())
        )

        out.by_category = [
            {
                "Category": category,
                "Cost (Rs)": round(cost),
            }
            for category, cost in sorted(
                categories.items(),
                key=lambda kv: -kv[1],
            )
        ]

        out.validation = {
            "status": "blocked" if validation_errors else "ready",
            "errors": validation_errors,
            "warnings": validation_warnings,
        }
        out.warnings = [
            *validation_errors,
            *validation_warnings,
        ]

        return out