#!/bin/sh
# Ouvre l'interface autopostule (Linux / macOS).
cd "$(dirname "$0")" && exec .venv/bin/autopostule interface "$@"
