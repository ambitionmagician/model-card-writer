# Model Card Writer

Generate a Hugging Face `README.md` and an Ollama `Modelfile` from one UTF-8 JSON spec. The tool runs locally and does not download models, evaluate benchmarks, or publish files.

## Install and run

Save the script as `model_card_writer.py`. Use Python 3.8 or newer; no packages are needed.

    python model_card_writer.py --help
    python model_card_writer.py --spec spec.json --validate-only
    python model_card_writer.py --spec spec.json --out-dir generated

Validation reports missing required fields together and does not create the output directory. Invalid input or an I/O failure produces a nonzero exit status.

## Example spec

The identifiers and descriptions below are illustrative. Replace them with your model's actual metadata.

    {
      "name": "Example summarizer",
      "base_model": "example-org/example-base",
      "ollama_from": "example-base:latest",
      "license": "apache-2.0",
      "tags": ["summarization"],
      "trained_on": "Human-written summaries of public-domain essays.",
      "training_recipe": "Supervised fine-tuning on essay and summary pairs.",
      "results": [],
      "intended_use": "Draft short summaries for editorial review.",
      "limitations": "May omit qualifiers or misstate details.",
      "params": {"temperature": 0.2, "num_ctx": 4096},
      "system": "Summarize the supplied essay. Preserve important qualifications."
    }

Required fields are `base_model`, `license`, `trained_on`, `training_recipe`, `results`, `intended_use`, and `limitations`. The other fields shown are optional.

- **Results:** Supply an array of objects with exactly `name` (single-line text) and `score` (JSON number). Include the metric and scale in the name when needed. An empty array explicitly indicates no reported scores. Missing scores are errors, not zeroes; numbers are read as decimals without float rounding.
- **Metadata:** Use the Hugging Face license identifier and base model ID appropriate to your model. Tags default to an empty list. Narrative fields support Markdown and are emitted as authored.
- **Ollama:** `FROM` defaults to `base_model`. Set `ollama_from` when the Ollama model has a different identifier. Parameters accept numbers, booleans, and nonblank single-line strings without double quotes or backslashes. An array emits repeated `PARAMETER` lines, useful for multiple stop sequences. The optional system prompt may span lines but cannot contain three consecutive double quotes.

## Limits and file handling

Specs are limited to 4 MiB. Unknown fields and duplicate JSON keys are rejected. Validation checks structure, not license validity, model availability, factual accuracy, or parameter compatibility with your Ollama version. The tool does not convert weights; `FROM` must reference something your Ollama installation can load.

Generation creates the output directory if needed and **replaces existing `README.md` and `Modelfile` files**. Use a dedicated output directory to avoid overwriting project documentation. Both files are staged before replacement; replacement is atomic per file, not transactional across the pair.
