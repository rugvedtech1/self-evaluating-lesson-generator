"""Self-evolution from the command line.

  PYTHONPATH=backend python -m app.evolution.cli status                     # patterns + prompt versions (free)
  PYTHONPATH=backend python -m app.evolution.cli validate                   # validate ACTIVE prompt (~$0.02)
  PYTHONPATH=backend python -m app.evolution.cli evolve [--min-occurrences N]   # full cycle (~$0.02 if a candidate)
  PYTHONPATH=backend python -m app.evolution.cli rollback [--to-version N]
"""

import argparse

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import session_scope
from app.evolution.cycle import rollback_generator_prompt
from app.evolution.patterns import sync_failure_patterns
from app.evolution.runtime import EvolutionService, build_validator
from app.generator.prompts import DEFAULT_GENERATOR_INSTRUCTIONS
from app.services.prompts import ensure_active_prompt, list_prompt_versions


def _status() -> None:
    with session_scope() as db:
        active = ensure_active_prompt(db, "generator", DEFAULT_GENERATOR_INSTRUCTIONS)
        patterns = sync_failure_patterns(db, active.id)
        print(f"\nACTIVE GENERATOR PROMPT: v{active.version}")
        print("\nFAILURE PATTERNS (runs using the active prompt):")
        for p in patterns or []:
            print(f"  {p.occurrence_count:>3}x  [{p.status:<9}] {p.description}")
        if not patterns:
            print("  none recorded yet")
        print("\nVERSIONS:")
        for v in list_prompt_versions(db, "generator"):
            report = v.validation_report or {}
            check = "" if not report else (" validation: PASSED" if report.get("passed") else " validation: FAILED")
            print(f"  v{v.version:<3} {v.status:<10}{check}  {v.change_reason or ''}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("validate")
    evolve = sub.add_parser("evolve")
    evolve.add_argument("--min-occurrences", type=int, default=None)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--to-version", type=int, default=None)
    args = parser.parse_args(argv)
    configure_logging(get_settings().log_level)

    if args.command == "status":
        _status()
    elif args.command == "validate":
        with session_scope() as db:
            text = ensure_active_prompt(db, "generator", DEFAULT_GENERATOR_INSTRUCTIONS).content
        report = build_validator()(text)
        for case in report.cases:
            print(f"  {case.case:<22} {case.overall_status or 'ERROR'}  failed={case.failed_criteria} {case.error or ''}")
        print(f"\nVALIDATION {'PASSED' if report.passed else 'FAILED'}")
    elif args.command == "evolve":
        outcome = EvolutionService().run(args.min_occurrences or get_settings().evolution_min_occurrences)
        if outcome is None:
            print("Cycle failed: see the logs above.")
            return 1
        print(f"\n{outcome.action.upper()}: {outcome.message}")
        for rule in outcome.added_rules:
            print(f"  + {rule}")
    elif args.command == "rollback":
        with session_scope() as db:
            target = rollback_generator_prompt(db, args.to_version)
            print(f"Rolled back: v{target.version} is now the active generator prompt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
