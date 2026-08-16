"""Import benchmark metadata from a cloned benchmarks repository."""
from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from comp_eval_platform.core.models import Benchmark, Category


REPOSITORY_RE = re.compile(r"^- Source repository:\s*(\S+\s*)$", re.MULTILINE)
COMMIT_RE = re.compile(r"^- Source commit:\s*([0-9a-fA-F]+)\s*$", re.MULTILINE)
SEED_RE = re.compile(r"^- Generation seed:\s*(\d+)\s*$", re.MULTILINE)


class Command(BaseCommand):
	help = "Import benchmark metadata from README files in a benchmarks repo."

	def add_arguments(self, parser):
		parser.add_argument(
			"--repo-path",
			required=True,
			help="Path to the cloned benchmarks/ directory.",
		)

	def handle(self, *args, **options):
		repo_path = Path(options["repo_path"])
		if not repo_path.exists():
			raise CommandError(f"Repository path does not exist: {repo_path}")
		if not repo_path.is_dir():
			raise CommandError(f"Repository path is not a directory: {repo_path}")

		category, _ = Category.objects.get_or_create(name="default")

		created = 0
		updated = 0
		skipped = 0

		for benchmark_dir in sorted(path for path in repo_path.iterdir() if path.is_dir()):
			readme_path = benchmark_dir / "README.md"
			if not readme_path.exists():
				skipped += 1
				continue

			try:
				name, repository, commit_hash, seed = self.parse_readme(readme_path)
			except ValueError as exc:
				skipped += 1
				self.stdout.write(self.style.WARNING(f"skipped {benchmark_dir.name}: {exc}"))
				continue

			benchmark, was_created = Benchmark.objects.update_or_create(
				name=name,
				defaults=dict(
					category=category,
					repository=repository,
					hash=commit_hash,
					extra={"seed": seed},
					published=True,
				),
			)
			if was_created:
				created += 1
			else:
				updated += 1

			data_path = readme_path.with_name("data.json")
			data_path.write_text(
				json.dumps(
					{
						"name": name,
						"repository": repository,
						"hash": commit_hash,
						"seed": seed,
					}
				),
				encoding="utf-8",
			)

		self.stdout.write(
			self.style.SUCCESS(
				f"Imported benchmarks: created {created}, updated {updated}, skipped {skipped}."
			)
		)

	def parse_readme(self, readme_path: Path) -> tuple[str, str, str, int]:
		text = readme_path.read_text(encoding="utf-8")

		name_line = next((line.strip() for line in text.splitlines() if line.strip()), None)
		name = name_line[2:].strip() if name_line and name_line.startswith("# ") else name_line
		if not name:
			raise ValueError("missing benchmark name")

		repository = self._match(REPOSITORY_RE, text, "missing source repository")
		commit_hash = self._match(COMMIT_RE, text, "missing source commit")
		seed_text = self._match(SEED_RE, text, "missing generation seed")

		try:
			seed = int(seed_text)
		except ValueError as exc:
			raise ValueError("invalid generation seed") from exc

		return name, repository, commit_hash, seed

	@staticmethod
	def _match(pattern: re.Pattern[str], text: str, error: str) -> str:
		match = pattern.search(text)
		if not match:
			raise ValueError(error)
		return match.group(1).strip()
