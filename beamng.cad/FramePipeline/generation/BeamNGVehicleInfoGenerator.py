"""Generate BeamNG vehicle-selector metadata and a default configuration.

This script is standalone and uses only the Python standard library.  Edit
``vehicle_info_settings.json`` or pass another settings file with ``--settings``.

Generated files:

* info.json                 - vehicle-level selector metadata and paints
* <config>.pc               - default part configuration
* info_<config>.json        - selector metadata for that configuration

The generated configuration automatically selects the part and slotType found
in the generated shell JBeam.  Additional slot selections can be supplied in
the settings file's ``parts`` object.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_SETTINGS = SCRIPT_DIRECTORY / "vehicle_info_settings.json"


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must contain a JSON object.")
    return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, indent=2, ensure_ascii=False)
        file.write("\n")


def require_string(settings: dict, key: str) -> str:
    value = settings.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Setting {key!r} must be a non-empty string.")
    return value.strip()


def validate_identifier(value: str, label: str) -> None:
    if not re.fullmatch(r"[a-z0-9_]+", value):
        raise ValueError(
            f"{label} must contain only lower-case letters, numbers, and underscores: "
            f"{value!r}"
        )


def read_generated_part(jbeam_path: Path, requested_part: str | None):
    root = read_json(jbeam_path)
    if requested_part:
        if requested_part not in root:
            raise RuntimeError(
                f"Part {requested_part!r} was not found in {jbeam_path.name}."
            )
        part_name = requested_part
    elif len(root) == 1:
        part_name = next(iter(root))
    else:
        raise RuntimeError(
            "The generated JBeam contains multiple parts. Set generatedPartName."
        )

    part = root[part_name]
    slot_type = part.get("slotType")
    if not isinstance(slot_type, str) or not slot_type:
        raise RuntimeError(f"JBeam part {part_name!r} has no slotType.")

    information = part.get("information", {})
    return part_name, slot_type, information


def normalize_years(settings: dict) -> dict:
    years = settings.get("years", {})
    if not isinstance(years, dict):
        raise ValueError("years must be an object containing min and max.")
    minimum = int(years.get("min"))
    maximum = int(years.get("max"))
    if minimum > maximum:
        raise ValueError("years.min cannot be greater than years.max.")
    return {"min": minimum, "max": maximum}


def normalize_paint(name: str, paint: dict) -> dict:
    if not isinstance(paint, dict):
        raise ValueError(f"Paint {name!r} must be an object.")
    color = paint.get("baseColor")
    if not isinstance(color, list) or len(color) != 4:
        raise ValueError(f"Paint {name!r} baseColor must contain four numbers.")

    result = {
        "baseColor": [float(value) for value in color],
        "clearcoat": float(paint.get("clearcoat", 0.0)),
        "clearcoatRoughness": float(paint.get("clearcoatRoughness", 0.0)),
        "metallic": float(paint.get("metallic", 0.0)),
        "roughness": float(paint.get("roughness", 0.5)),
    }
    if paint.get("class"):
        result["class"] = str(paint["class"])

    for property_name in (
        "clearcoat",
        "clearcoatRoughness",
        "metallic",
        "roughness",
    ):
        if not 0.0 <= result[property_name] <= 1.0:
            raise ValueError(
                f"Paint {name!r} property {property_name} must be between 0 and 1."
            )

    return result


def build_main_info(settings: dict, config_id: str) -> dict:
    paints_setting = settings.get("paints", {})
    if not isinstance(paints_setting, dict) or not paints_setting:
        raise ValueError("At least one paint must be defined.")
    paints = {
        name: normalize_paint(name, paint)
        for name, paint in paints_setting.items()
    }

    default_paint = require_string(settings, "defaultPaintName1")
    if default_paint not in paints:
        raise ValueError(
            f"defaultPaintName1 {default_paint!r} does not match a defined paint."
        )

    result = {
        "Name": require_string(settings, "name"),
        "Brand": require_string(settings, "brand"),
        "Author": require_string(settings, "author"),
        "Country": require_string(settings, "country"),
        "Description": require_string(settings, "description"),
        "Body Style": require_string(settings, "bodyStyle"),
        "Type": require_string(settings, "type"),
        "Population": int(settings.get("population", 0)),
        "default_pc": config_id,
        "defaultPaintName1": default_paint,
        "Years": normalize_years(settings),
        "paints": paints,
        "multiPaintSetups": settings.get("multiPaintSetups", []),
        "libraryPaints": settings.get("libraryPaints", []),
    }

    derby_class = settings.get("derbyClass")
    if derby_class:
        result["Derby Class"] = str(derby_class)

    return result


def build_configuration_info(
    settings: dict,
    default_paint: str,
    generated_information: dict,
) -> dict:
    config = settings.get("configuration", {})
    if not isinstance(config, dict):
        raise ValueError("configuration must be an object.")

    value = config.get("value", generated_information.get("value", 0))
    result = {
        "Config Type": str(config.get("type", "Custom")),
        "Configuration": str(config.get("name", "Generated Frame")),
        "Description": str(
            config.get(
                "description",
                "Generated deformable frame using the material-tuned JBeam shell.",
            )
        ),
        "Population": int(config.get("population", 0)),
        "Value": int(value),
        "Years": normalize_years(settings),
        "defaultPaintName1": default_paint,
    }

    # Performance and complete-vehicle mass are intentionally optional.  The
    # material tuner's mass is frame-only and must not be mislabeled as total
    # vehicle weight in the selector.
    optional_fields = {
        "weight": "Weight",
        "power": "Power",
        "torque": "Torque",
        "topSpeed": "Top Speed",
        "drivetrain": "Drivetrain",
        "transmission": "Transmission",
        "fuelType": "Fuel Type",
        "propulsion": "Propulsion",
        "inductionType": "Induction Type",
        "offRoadScore": "Off-Road Score",
    }
    for setting_name, output_name in optional_fields.items():
        if config.get(setting_name) is not None:
            result[output_name] = config[setting_name]

    if result.get("Weight") and result.get("Power"):
        result["Weight/Power"] = result["Weight"] / result["Power"]

    return result


def build_pc(
    settings: dict,
    model_id: str,
    main_part_name: str,
    generated_part_name: str,
    generated_slot_type: str,
) -> dict:
    configured_parts = settings.get("parts", {})
    if not isinstance(configured_parts, dict):
        raise ValueError("parts must be an object mapping slot names to part names.")

    parts = {str(slot): str(part) for slot, part in configured_parts.items()}
    if generated_slot_type == "main":
        if generated_part_name != main_part_name:
            raise ValueError(
                "A standalone main JBeam must use the same generated part name "
                f"and mainPartName ({generated_part_name!r} != {main_part_name!r})."
            )
    else:
        existing = parts.get(generated_slot_type)
        if existing and existing != generated_part_name:
            raise ValueError(
                f"parts already assigns {generated_slot_type!r} to {existing!r}; "
                f"the generated JBeam part is {generated_part_name!r}."
            )
        parts[generated_slot_type] = generated_part_name

    variables = settings.get("variables", {})
    if not isinstance(variables, dict):
        raise ValueError("variables must be an object.")

    return {
        "format": 2,
        "mainPartName": main_part_name,
        "model": model_id,
        "parts": dict(sorted(parts.items())),
        "vars": variables,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate BeamNG info.json, a default .pc, and config metadata."
    )
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output vehicle directory. Defaults to the settings file's directory.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing generated metadata files.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    settings_path = arguments.settings.resolve()
    settings = read_json(settings_path)
    output_directory = (
        arguments.output_dir.resolve()
        if arguments.output_dir is not None
        else settings_path.parent
    )

    model_id = require_string(settings, "modelId")
    config_id = require_string(settings, "defaultConfig")
    main_part_name = require_string(settings, "mainPartName")
    validate_identifier(model_id, "modelId")
    validate_identifier(config_id, "defaultConfig")

    jbeam_setting = require_string(settings, "generatedJBeam")
    jbeam_path = Path(jbeam_setting)
    if not jbeam_path.is_absolute():
        jbeam_path = settings_path.parent / jbeam_path
    jbeam_path = jbeam_path.resolve()

    requested_part = settings.get("generatedPartName") or None
    generated_part_name, generated_slot_type, generated_information = (
        read_generated_part(jbeam_path, requested_part)
    )

    main_info = build_main_info(settings, config_id)
    configuration_info = build_configuration_info(
        settings,
        main_info["defaultPaintName1"],
        generated_information,
    )
    configuration = build_pc(
        settings,
        model_id,
        main_part_name,
        generated_part_name,
        generated_slot_type,
    )

    info_path = output_directory / "info.json"
    pc_path = output_directory / f"{config_id}.pc"
    config_info_path = output_directory / f"info_{config_id}.json"

    output_paths = [info_path, pc_path, config_info_path]
    existing_paths = [path for path in output_paths if path.exists()]
    if existing_paths and not arguments.force:
        names = ", ".join(path.name for path in existing_paths)
        raise FileExistsError(
            f"Refusing to replace {names}. Re-run with --force after checking them."
        )

    write_json(info_path, main_info)
    write_json(pc_path, configuration)
    write_json(config_info_path, configuration_info)

    print(f"Generated part:  {generated_part_name}")
    print(f"Target slot:     {generated_slot_type}")
    print(f"Main part:       {main_part_name}")
    print(f"Vehicle model:   {model_id}")
    print(f"Wrote:           {info_path}")
    print(f"Wrote:           {pc_path}")
    print(f"Wrote:           {config_info_path}")
    print()
    print(
        "Place these files, the final JBeam, and the DAE in "
        f"vehicles/{model_id}/ inside the mod."
    )


if __name__ == "__main__":
    main()
