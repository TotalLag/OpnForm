#!/usr/bin/env python3
"""Fail when upstream-only deployment providers reappear in fork workflows."""

from pathlib import Path

FORBIDDEN = {
    "NuxtHub action": "nuxt-hub/action",
    "NuxtHub CLI": "nuxthub@",
    "Amplify deployment hook": "AMPLIFY_DEPLOY_URL",
    "Vapor deployment command": "vapor deploy",
    "Vapor production token": "VAPOR_API_TOKEN",
}

violations: list[str] = []
for workflow in sorted(Path(".github/workflows").glob("*.y*ml")):
    for line_number, line in enumerate(workflow.read_text().splitlines(), start=1):
        for label, needle in FORBIDDEN.items():
            if needle.lower() in line.lower():
                violations.append(f"{workflow}:{line_number}: {label}")

if violations:
    print("Fork deployment boundary violations:")
    print("\n".join(f"- {violation}" for violation in violations))
    raise SystemExit(1)

print("Fork deployment boundaries passed")
