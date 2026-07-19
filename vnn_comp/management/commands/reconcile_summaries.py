"""Re-freeze validation-step summaries against the stored Result rows.

The scorer drops an all-unknown/all-timeout category (delete_empty_categories), so runs
finished before the reconciliation existed froze a zeroed verdict tally. This recomputes
each done check-results step's summary from its (immutable) Result rows and scorer log.
"""
from django.core.management.base import BaseCommand

from comp_eval_platform.core.models.execution import StepStatus, TaskStep

from vnn_comp import kinds
from vnn_comp.steps import compute_check_summary, freeze_check_summary


class Command(BaseCommand):
    help = "Recompute frozen verdict tallies for finished VNN validation steps."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change without writing.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        steps = TaskStep.objects.filter(kind=kinds.CHECK_RESULTS, status=StepStatus.DONE)
        changed = 0
        for step in steps:
            before = (step.payload or {}).get("summary", {}).get("verdicts")
            if dry_run:
                summary, _ = compute_check_summary(step)
                after = summary["verdicts"] if summary else None
            elif freeze_check_summary(step):
                after = (step.payload or {}).get("summary", {}).get("verdicts")
            else:
                after = None
            if after != before:
                changed += 1
                self.stdout.write(f"step {step.id} (task {step.task_id}): {before} -> {after}")
        verb = "would change" if dry_run else "updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {changed} of {steps.count()} step(s)."))
