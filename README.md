# Limits-2026

This repository contains the source material for a LIMITS paper on per-request resource consumption and sustainability modeling for HTTP systems.

## Repository structure

```text
.
|-- paper.tex            # Main LaTeX source for the paper
|-- bib.bib              # Bibliography
|-- acmart.cls           # ACM article class used for the paper
|-- Makefile             # Build and cleanup helpers for the LaTeX paper
|-- data/                # Collected and processed experiment data in JSON form
|-- scripts/             # Helper scripts used from the paper workflow
|-- code/                # Benchmark application, configs, and experiment scripts
|   |-- manage.py
|   |-- requirements.txt
|   |-- docker-compose-*.yml
|   |-- nginx/           # Nginx setup for modeled header experiments
|   |-- scripts/         # Benchmark and analysis scripts
|   |-- todo_project/    # Django project
|   `-- todoapp/         # Django app used in the experiments
`-- paper.pdf            # Built paper output, when generated
```

## Notes

- The paper sources live at the repository root.
- The `code/` directory contains the experimental web application and benchmarking setup used to support the paper.
- The `data/` and `scripts/` directories contain supporting artifacts used to generate tables and compare measurement results.

To build the paper locally:

```bash
make build
```
