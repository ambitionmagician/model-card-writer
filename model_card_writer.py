#!/usr/bin/env python3
"""Generate a Hugging Face model card and an Ollama Modelfile from JSON."""

import argparse
import json
import os
import re
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path


MAX_BYTES = 4 * 1024 * 1024
REQUIRED = (
    "base_model", "license", "trained_on", "training_recipe",
    "results", "intended_use", "limitations",
)
OPTIONAL = ("name", "tags", "params", "system", "ollama_from")
# A portable, single-token model reference, not a shell command or URL.
MODEL_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@+-]*\Z")
PARAM_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
BAD_TEXT = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]")


class SpecError(ValueError):
    """The input cannot be interpreted unambiguously."""


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise SpecError(f"duplicate JSON key: {ascii(key)}")
        obj[key] = value
    return obj


def reject_constant(token):
    raise SpecError(f"{token} is not a JSON number")


def load_spec(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SpecError(f"spec exceeds {MAX_BYTES} bytes")
    return json.loads(
        data.decode("utf-8-sig"),
        object_pairs_hook=unique_object,
        parse_float=Decimal,
        parse_int=Decimal,
        parse_constant=reject_constant,
    )


def valid_text(value, single_line=False):
    if not isinstance(value, str) or not value.strip():
        return False
    if BAD_TEXT.search(value.replace("\r\n", "\n")):
        return False
    return not single_line or (
        len(value.splitlines(True)) == 1
        and not any(c in value for c in "\r\n\t\u2028\u2029")
    )


def validate(spec):
    if not isinstance(spec, dict):
        return ["root must be a JSON object"]
    errors = [f"missing required field: {k}" for k in REQUIRED if k not in spec]
    for key in sorted(spec.keys() - set(REQUIRED + OPTIONAL)):
        errors.append(f"unknown field: {ascii(key)}")

    for key in ("name", "license", "trained_on", "training_recipe",
                "intended_use", "limitations", "system"):
        if key in spec and not valid_text(spec[key], key in ("name", "license")):
            errors.append(f"{key}: expected nonblank text without control characters")
    for key in ("base_model", "ollama_from"):
        if key in spec and not (
            isinstance(spec[key], str) and MODEL_REF.fullmatch(spec[key])
        ):
            errors.append(f"{key}: expected a single model identifier")

    tags = spec.get("tags", [])
    if not isinstance(tags, list) or not all(valid_text(t, True) for t in tags):
        errors.append("tags: expected an array of nonblank single-line strings")

    if "results" in spec:
        rows = spec["results"]
        if not isinstance(rows, list):
            errors.append("results: expected an array")
        else:
            for i, row in enumerate(rows):
                label = f"results[{i}]"
                if not isinstance(row, dict) or row.keys() != {"name", "score"}:
                    errors.append(f"{label}: expected exactly name and score")
                    continue
                if not valid_text(row["name"], True):
                    errors.append(f"{label}.name: expected a nonblank single line")
                if not isinstance(row["score"], Decimal):
                    errors.append(f"{label}.score: expected a JSON number")

    params = spec.get("params", {})
    if not isinstance(params, dict):
        errors.append("params: expected an object")
    else:
        for key, value in params.items():
            if not PARAM_NAME.fullmatch(key):
                errors.append(f"params: invalid parameter name {ascii(key)}")
                continue
            values = value if isinstance(value, list) else [value]
            if not values:
                errors.append(f"params.{key}: empty parameter list")
            for item in values:
                if isinstance(item, (bool, Decimal)):
                    continue
                # Use quoted single-line strings; avoid ambiguous delimiters.
                if not (valid_text(item, True) and '"' not in item
                        and "\\" not in item):
                    errors.append(
                        f"params.{key}: expected numbers, booleans, or nonblank "
                        "single-line strings without double quotes or backslashes"
                    )
                    break

    system = spec.get("system")
    if isinstance(system, str) and '"""' in system:
        errors.append('system: cannot contain the Ollama delimiter """')
    return errors


def yaml_string(text):
    # JSON quoted strings are YAML-compatible. Escape Unicode line separators.
    return (json.dumps(text, ensure_ascii=False)
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def table_cell(text):
    # Entities prevent user-supplied pipes or inline markup changing the table.
    return "".join(c if c.isalnum() or c == " " else f"&#{ord(c)};" for c in text)


def render_card(spec):
    tags = ", ".join(yaml_string(t) for t in spec.get("tags", []))
    lines = [
        "---",
        f"license: {yaml_string(spec['license'])}",
        f"base_model: {yaml_string(spec['base_model'])}",
        f"tags: [{tags}]",
        "---", "",
        f"# {spec.get('name', spec['base_model'])}", "",
    ]
    for heading, key in (
        ("Intended use", "intended_use"), ("Training data", "trained_on"),
        ("Training recipe", "training_recipe"),
    ):
        lines.extend([f"## {heading}", "", spec[key].strip(), ""])
    lines.extend(["## Evaluation results", ""])
    if spec["results"]:
        lines.extend(["| Benchmark | Score |", "| --- | ---: |"])
        for row in spec["results"]:
            lines.append(f"| {table_cell(row['name'])} | {row['score']} |")
    else:
        lines.append("No benchmark scores provided.")
    lines.extend(["", "## Limitations", "", spec["limitations"].strip(), ""])
    return "\n".join(lines).replace("\r\n", "\n")


def render_modelfile(spec):
    lines = [f"FROM {spec.get('ollama_from', spec['base_model'])}"]
    for key, value in spec.get("params", {}).items():
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str):
                token = f'"{item}"'
            elif isinstance(item, bool):
                token = str(item).lower()
            else:
                token = str(item)
            lines.append(f"PARAMETER {key} {token}")
    if "system" in spec:
        # Separate delimiters from content, including trailing quote characters.
        lines.extend(['SYSTEM """', spec["system"], '"""'])
    return ("\n".join(lines) + "\n").replace("\r\n", "\n")


def write_outputs(directory, outputs):
    directory.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for name, content in outputs:
            target = directory / name
            if target.is_dir():
                raise IsADirectoryError(f"output is a directory: {target}")
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n",
                prefix=".model-card-", dir=directory, delete=False,
            ) as tmp:
                staged.append((Path(tmp.name), target))
                tmp.write(content)
        for source, target in staged:
            os.replace(source, target)
    finally:
        for source, _ in staged:
            try:
                source.unlink()
            except FileNotFoundError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="UTF-8 JSON spec")
    parser.add_argument("--out-dir", type=Path, default=Path("."),
                        help="output directory (default: current directory)")
    parser.add_argument("--validate-only", action="store_true",
                        help="validate the spec without creating files or directories")
    args = parser.parse_args(argv)
    try:
        spec = load_spec(args.spec)
        errors = validate(spec)
        if errors:
            raise SpecError("\n".join(errors))
        if args.validate_only:
            print("Spec is valid.")
            return 0
        outputs = (("README.md", render_card(spec)),
                   ("Modelfile", render_modelfile(spec)))
        for name, _ in outputs:
            target = args.out_dir / name
            if target.exists() and target.samefile(args.spec):
                raise SpecError(f"output would overwrite input: {target}")
        write_outputs(args.out_dir, outputs)
        print(f"Wrote README.md and Modelfile to {args.out_dir}")
        return 0
    except (OSError, ValueError, InvalidOperation, RecursionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
