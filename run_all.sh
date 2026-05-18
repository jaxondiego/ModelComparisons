#!/usr/bin/env bash
set -euo pipefail

print_header() {
    echo ""
    echo "╔══════════════════════════════════════════════════════╗"
    printf  "║  %-52s  ║\n" "$1"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
}

check_env() {
    if [ -z "${OPENROUTER_API_KEY:-}" ]; then
        echo "ERROR: OPENROUTER_API_KEY is not set."
        echo "  export OPENROUTER_API_KEY=your_key_here"
        exit 1
    fi
}

check_env

print_header "STEP 1: Running model evaluations"
uv run python runner.py

print_header "STEP 2: Judging responses"
uv run python judge.py

print_header "STEP 3: Analyzing results & generating charts"
uv run python analyze.py

echo ""
echo "════════════════════════════════════════════════════════"
echo "  All done!  Results saved to results/"
echo "  Charts:   results/charts/"
echo "  Scores:   results/scores.json"
echo "  Report:   results/report.md"
echo "════════════════════════════════════════════════════════"
echo ""
