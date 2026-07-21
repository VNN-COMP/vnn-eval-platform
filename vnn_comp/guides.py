"""The how-to copy for VNN-COMP's two submission pages.

Kept out of ``competition.py``, which is the seam wiring rather than prose. The
shell renders these; it knows nothing about VNNLIB, onnx, or our scripts.

The pipelines below must stay in step with ``VNNCompetition.build_steps`` — they
describe the steps a submitter watches on the detail page, under the same names
(the frontend's ``KIND_LABEL``). Optional steps are named in the details rather
than the strip, which shows the line every submission takes.
"""
from comp_eval_platform.results import Guide

TOOL_SKELETON = "https://github.com/VNN-COMP/example_toolkit"
BENCHMARK_SKELETON = "https://github.com/VNN-COMP/example_benchmark"
RULES = "https://github.com/VNN-COMP/vnncomp2026/blob/main/rules.md"

_CE_1_0 = """sat
((X_0 0.02500000074505806)
 (X_1 0.97500000000000000)
 (Y_0 -0.03500000023705806)
 (Y_1 0.32500000072225301)
 (Y_2 0.02500000094505020))"""

_CE_2_0 = """sat
X float32 [1,2]
0.1
0.2
Y float32 [1]
0.3"""


def toolkit_guide() -> Guide:
    return Guide(
        intro="How a toolkit submission is validated and run. To submit one, or to look "
              "at submissions that already ran, use the submissions page.",
        pipeline=[
            {
                "title": "Create Submission",
                "details": [
                    "The submission is recorded with what you chose on the form: the repository "
                    "and commit, the benchmarks to run, and which stages run as root. Nothing "
                    "runs on a worker yet, so this step passes immediately.",
                    "That record fixes everything the pipeline does afterwards, which is what "
                    "makes a run reproducible — the commit is resolved and stored even if you "
                    "submitted a branch rather than a hash.",
                ],
            },
            {
                "title": "Assign Worker",
                "details": [
                    "The task waits for a worker and attaches it. Depending on how the "
                    "deployment is configured that is either an AWS instance created from the "
                    "AMI you selected, or a Docker container on the backend host. The rest of "
                    "the pipeline is identical either way: every step reaches the worker over SSH.",
                    "This is the queueing stage you see before any repository work starts. On "
                    "AWS, a submission tied to an ENI reuses that network interface here, so the "
                    "machine comes up with the expected network identity.",
                ],
            },
            {
                "title": "Install Toolkit",
                "details": [
                    "Your repository is cloned at the submitted commit and the scripts directory "
                    "you named must contain `install_tool.sh`, `prepare_instance.sh` and "
                    "`run_instance.sh`. The submission fails here if any of the three is missing, "
                    "or if the scripts directory is wrong.",
                    "`install_tool.sh v1` then runs to install your solver, its dependencies and "
                    "environments. Installs are retried rather than failed outright, since a "
                    "network hiccup is not a broken submission.",
                    "Install as root only when the install genuinely needs it. A root install "
                    "leaves root-owned files in the home directory that later unprivileged steps "
                    "— including the scorer — cannot read, which fails a run that would otherwise "
                    "have worked.",
                ],
            },
            {
                "title": "Post-Installation Script",
                "details": [
                    "The script from the “Post installation script” field runs on the worker. "
                    "This is the place for anything that depends on the machine the tool was just "
                    "built on, licence activation above all.",
                    "What you type into the form wins over any `post_install.sh` in your "
                    "repository. A submission with neither is a no-op rather than a failure.",
                    "Either side of this step is where the optional pauses land: enable the manual "
                    "installation pause to hold the task before it and finish the install by hand, "
                    "and the pause after post-installation to inspect the machine before the "
                    "benchmarks start. A paused task waits for you and does not time out on its own.",
                ],
            },
            {
                "title": "Run Benchmark",
                "details": [
                    "One step per selected benchmark, so a benchmark that fails does not take the "
                    "others with it. For each instance the worker runs `prepare_instance.sh v1 "
                    "<category> <onnx> <vnnlib>` and then `run_instance.sh v1 <category> <onnx> "
                    "<vnnlib> <result-file> <timeout>`. For VNN-COMP the category is the benchmark "
                    "name.",
                    "`prepare_instance.sh` is capped at 600 s and `run_instance.sh` at that "
                    "instance's own timeout from `instances.csv`; a nonzero exit from "
                    "`prepare_instance.sh` skips the rest of that benchmark, as the rules require.",
                    "A wall-clock cap on the whole benchmark backs those up, for a tool that hangs "
                    "past them. It times out only that benchmark and the task continues with the "
                    "next one. The verdicts and runtimes land in a `results.csv` you can read on "
                    "the submission page while it fills up.",
                ],
            },
            {
                "title": "Validate Counterexamples",
                "details": [
                    "The official scorer re-checks every counterexample the run produced, "
                    "confirming the witness really does violate the property it claims to. This is "
                    "what the overview on the submission page reports: a `sat` the scorer cannot "
                    "reproduce is counted as invalid or missing rather than as a solved instance.",
                    "It is a step of its own rather than part of the run, so its tallies get their "
                    "own log and a problem with the scorer is not mistaken for your tool failing. "
                    "A benchmark is only finished once its validation is.",
                ],
            },
            {
                "title": "Export Results",
                "details": [
                    "Only for submissions that enabled export. The run's `results.csv` and its "
                    "counterexamples are pushed to the competition's results repository, and the "
                    "step offers the same files as a zip download.",
                ],
            },
            {
                "title": "Shutdown",
                "details": [
                    "The worker is terminated once every benchmark has run. The submission page "
                    "stays available afterwards, so the logs, the results and the scorer's "
                    "verdicts can all be read later — but the worker itself is gone, so anything "
                    "not collected by then is gone with it.",
                ],
            },
        ],
        sections=[
            {
                "heading": "What Your Repository Must Contain",
                "blocks": [
                    {"type": "text", "text":
                        f"The [toolkit skeleton repository]({TOOL_SKELETON}) "
                        "is the minimal layout the submission system can validate. It has the "
                        "required scripts with their argument parsing already in place and `TODO`s "
                        "where your tool-specific logic goes. Its scripts sit at the repository "
                        "root, so its scripts directory would be submitted as the repository root."},
                    {"type": "bullets", "items": [
                        "`install_tool.sh` — installs the toolkit, once per worker. Called as "
                        "`install_tool.sh v1`; the argument is the interface version.",
                        "`prepare_instance.sh` — called before each instance as `prepare_instance.sh "
                        "v1 <category> <onnx> <vnnlib>`, to prepare whatever that instance needs. "
                        "Capped at 600 s, and a nonzero exit skips the rest of the benchmark.",
                        "`run_instance.sh` — runs one instance as `run_instance.sh v1 <category> "
                        "<onnx> <vnnlib> <result-file> <timeout>` and writes its verdict as the "
                        "first line of `<result-file>`. Capped at that instance's timeout from "
                        "`instances.csv`.",
                        "`post_install.sh` (optional) — a template for the post-installation step. "
                        "It is not run from your repository: paste its contents into the “Post "
                        "installation script” field on the submission form.",
                    ]},
                ],
            },
            {
                "heading": "Counterexamples",
                "blocks": [
                    {"type": "text", "text":
                        f"For VNNLIB 1.0 benchmarks, write satisfying counterexamples as the "
                        f"[VNN-COMP 2026 rules]({RULES}) describe, using the flat `X_i` and `Y_i` "
                        "variables:"},
                    {"type": "code", "code": _CE_1_0},
                    {"type": "text", "text":
                        "For VNNLIB 2.0 benchmarks, follow the [VNNLIB 2.0 standard]"
                        "(https://www.vnnlib.org/) (Sec. 5.3.1, command-line assignment):"},
                    {"type": "code", "code": _CE_2_0},
                ],
            },
            {
                "heading": "Choosing a Worker",
                "blocks": [
                    {"type": "text", "text":
                        "On AWS deployments the form asks for an AMI and an instance type, and the "
                        "machine it creates is used for the whole pipeline. Some AMIs are public "
                        "base images and some are configured for VNN-COMP by hand."},
                    {"type": "text", "text":
                        "Ubuntu AMIs can be looked up with [Canonical's AMI locator]"
                        "(https://cloud-images.ubuntu.com/locator/ec2/), and the MATLAB AMIs come "
                        "from [mathworks-ref-arch/matlab-on-aws]"
                        "(https://github.com/mathworks-ref-arch/matlab-on-aws). An AMI id can be "
                        "checked in the EC2 console or with `describe-images`; the instance types "
                        "are listed in the [EC2 instance type reference]"
                        "(https://docs.aws.amazon.com/ec2/latest/instancetypes/instance-types.html)."},
                    {"type": "note", "text":
                        "These options only apply to a deployment that runs submissions on AWS. "
                        "Where submissions run in Docker instead, the same field names the base "
                        "image the container is built from."},
                ],
            },
        ],
    )


def benchmark_guide() -> Guide:
    return Guide(
        intro="How a proposed benchmark is generated, checked, and published. To propose one, "
              "or to look at proposals that already ran, use the submissions page.",
        pipeline=[
            {
                "title": "Create Submission",
                "details": [
                    "The proposal is recorded with its repository and commit, and the layout you "
                    "declared on the form: where the generator lives, and where it writes its "
                    "networks, specifications and `instances.csv`. Nothing runs on a worker yet.",
                ],
            },
            {
                "title": "Assign Worker",
                "details": [
                    "The task waits for a worker and attaches it — an AWS instance or a Docker "
                    "container, depending on the deployment. This is the queueing stage you see "
                    "before any repository work starts.",
                ],
            },
            {
                "title": "Generate Instances",
                "details": [
                    "Your repository is cloned at the submitted commit. If it has an `install.sh` "
                    "at its root, that runs first, so the generator can install what it needs; the "
                    "generator itself then runs in an isolated Python environment.",
                    "The generator runs as `generate_properties.py <seed>` with the competition's "
                    "seed, which is the same for everyone. It is derived from the hash of the first "
                    "Ethereum block mined after the submission deadline: public and reproducible "
                    "afterwards, but nothing anyone could have tuned a benchmark to in advance.",
                    "What it produces is then normalized: the `instances.csv` rows are rewritten to "
                    "paths that resolve, and the declared network and specification files must "
                    "exist. This is the real check on whether a proposal is usable by the "
                    "competition tooling — the step fails when the generator produces no "
                    "`instances.csv`.",
                    "For a VNNLIB 1.0 proposal the specifications are also converted to VNNLIB 2.0. "
                    "That conversion is best-effort: if it fails, the run keeps the 1.0 files, logs "
                    "a warning, and carries on rather than failing your proposal.",
                    "The exact commit that was generated is recorded, so a benchmark proposed "
                    "without a hash stays reproducible, and every generated case is registered as "
                    "an instance of the benchmark.",
                ],
            },
            {
                "title": "Export to Benchmarks Repo",
                "details": [
                    "The generated files, plus a README naming the source repository and commit, "
                    "are pushed to the competition's benchmarks repository — which is where "
                    "toolkit runs read their benchmarks from.",
                    "A benchmark publishes itself once it has generated, exported and validated: a "
                    "successful run is the gate, there is no separate publish step. From then on it "
                    "can be selected when submitting a toolkit, and organizers can group it into "
                    "evaluation tracks.",
                ],
            },
            {
                "title": "Shutdown",
                "details": [
                    "The worker is terminated. The proposal's logs stay readable on its detail "
                    "page, which is where to look when generation did not do what you expected.",
                ],
            },
        ],
        sections=[
            {
                "heading": "What Your Repository Must Contain",
                "blocks": [
                    {"type": "text", "text":
                        f"The [benchmark skeleton repository]({BENCHMARK_SKELETON}) "
                        "is the minimal layout the submission system can validate. It has "
                        "`generate_properties.py` with the seed argument already parsed and `TODO`s "
                        "where your instance-generation logic goes, plus the output directories. "
                        "These sit at the repository root, so its scripts directory would be "
                        "submitted as the repository root."},
                    {"type": "bullets", "items": [
                        "`generate_properties.py` — takes the seed as its first argument and "
                        "generates the benchmark's instances on each run.",
                        "`instances.csv` — one row per instance, `<onnx_path>,<vnnlib_path>,"
                        "<timeout>`, written by the generator. Per the rules the timeouts must sum "
                        "to at most 6 hours across the benchmark.",
                        "`onnx/` and `vnnlib/` — the generated `.onnx` networks and `.vnnlib` "
                        "specifications. The form can point elsewhere if your repository uses "
                        "other directory names.",
                        "`install.sh` (optional) — runs at the repository root before generation, "
                        "for whatever your generator needs installed.",
                    ]},
                ],
            },
            {
                "heading": "After a Successful Run",
                "blocks": [
                    {"type": "text", "text":
                        "Once the automated checks pass, announce your proposal in the "
                        "competition's [GitHub repository](https://github.com/VNN-COMP) so the "
                        "organizers and the community can discuss and review it."},
                ],
            },
        ],
    )
