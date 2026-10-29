# Coach

Coach helps you prepare a conversation about a pull request. It returns zero, one or two coaching points, each with code evidence, a reason to discuss it, a question to ask, and a principle to explain.

This is an early local prototype. Its usefulness still needs your judgement on real PRs.

## Run

Requires Python 3.11 or newer with curses, Git, an authenticated GitHub CLI, and a running local Ollama model. There are no Python package dependencies. macOS and Linux are supported.

From this directory:

```sh
python3 -m coach https://github.com/suttree/commonground/pull/11 \
  --repo /Users/duncan/src/commonground
```

The default model is `qwen3.5:9b-coding`, which was already installed on the development machine. Select another installed model with `--model NAME` or `COACH_MODEL`. Coach never downloads models. The selected model must support Ollama's JSON schema output and `think: false`.

The UI opens immediately and shows progress while GitHub and Ollama respond. A local model can take several minutes. Press `q` to close. Closing the UI does not cancel a request already running in Ollama.

## Read and rate

- `f` shows the coaching conversation.
- `e` shows cited code with surrounding lines.
- `d` shows the collected diff.
- `c` shows which files and excerpts the model received.
- `n` and `p` move between points.
- `j` and `k`, arrow keys, or Page Up and Page Down scroll.
- `u`, `i`, `a` and `x` record useful, irrelevant, already understood or unsupported.
- `q` quits.

A result with no points can also be rated. Ratings are saved locally for manual comparison. They do not yet change future model output.

## Evidence and limits

Coach reads GitHub's PR title, description and commit IDs. It compares the head with the merge base and reads tracked source from those commits. It does not check out a branch, edit your repository, run repository code, or post comments.

The local repository's origin must match the PR. Both commits must exist locally. If a commit is missing, fetch it into your checkout before retrying. Automatic fetching and cloning are not implemented yet.

Context selection is deliberately small. It prioritises changed source and selects related files by names and symbols. It reserves space for related code, but does not trace every caller. The Context view discloses truncation and file coverage. Use repeated `--context-file path/to/file` arguments to include a caller, shared component or test you know matters.

Every finding must quote an exact supplied file excerpt at the stated line. Invalid citations, malformed output and model failures are errors. They are never converted into "no feedback". Citation checks establish that the code exists, not that the model's interpretation is correct.

The model can return three outcomes:

- `feedback`, with one or two points.
- `no_feedback`, when the reviewed material does not warrant a coaching conversation.
- `needs_context`, when missing evidence prevents a useful assessment.

No-feedback results are scoped to the supplied material, not a correctness guarantee for the PR.

All inference goes to a localhost Ollama endpoint. No hosted model support is included. GitHub receives the metadata request through `gh`. Obvious credential paths and binary files are excluded, but this is not a general secret scanner. Evidence, model output and ratings remain in `.coach/`, which is ignored by Git. Treat that directory as source code from the reviewed repository.

## Repeat an assessment

Collect evidence without calling a model:

```sh
python3 -m coach https://github.com/suttree/commonground/pull/11 \
  --repo /Users/duncan/src/commonground --collect-only > packet.json
```

Analyse the same evidence again, or reopen a saved result:

```sh
python3 -m coach --packet packet.json --json > review.json
python3 -m coach --open review.json
```

`--json` runs without the TUI. `--state-dir PATH` selects where evidence, results and ratings are saved. Reopening a result requires neither GitHub access nor a running model.

## Check the prototype

```sh
python3 -m unittest discover -s tests -v
```

The tests cover abstention, missing context, the two-point limit, invalid citations, source selection at historical commits, preserving uncommitted work, sensitive-path exclusions and terminal text handling.

The first real examples are Commonbound PRs #1 and #11. The useful question is whether you would have wanted the proposed conversation at the time. A plausible-sounding answer or a passing citation check is insufficient.
