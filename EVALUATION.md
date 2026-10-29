# First evaluation

These runs check the workflow and expose weaknesses. They do not establish that the model is a reliable coach. No results have been rated by the user yet.

The local model was `qwen3.5:9b-coding`. The source checkout was read at each PR's head and merge base. The app did not modify Commonbound or post feedback to GitHub.

## Observations

[PR #1](https://github.com/suttree/commonground/pull/1) updates GitHub Actions checkout. The model returned `no_feedback`. That is a reasonable result for coaching, but its explanation included a generic warning about possible breaking changes. The prompt now asks for a concise reason to abstain without speculative warnings. That wording change has not been rerun on this PR.

[PR #11](https://github.com/suttree/commonground/pull/11) adds notification emails. The first run returned `needs_context`, asking for the invitation model and delivery configuration. Those files were missing from the first selection. Its explanation also mixed a scheduled rake task with web-request latency. This was not a useful coaching result.

A subsequent draft had valid citations but made an unsupported claim that a scheduled rake task blocks the web server. It also labelled concerns as strengths. This demonstrates why matching source text is insufficient. A second model pass now checks relevance and causal claims, can correct a point's kind, and can discard every point. It cannot add replacement points.

The collector now reserves space for related code, recognises code symbols rather than ordinary capitalised words, and reads excerpts around changed lines. A focused rerun explicitly includes the invitation model, production configuration and reminder task. Its first response failed exact citation validation. No finding was accepted from that response. QQ now resolves a quote to its actual source line only if the quote has one unique match, ignoring leading and trailing whitespace. It still rejects ambiguous or invented quotations.

## Final check result

The final check discarded both points from the focused PR #11 draft and returned `no_feedback`. It correctly rejected the claim that the scheduled rake task blocks the web process, and recognised that scheduling was already called out in the description.

However, its reason for discarding the request-latency point was partly wrong. Rescuing an SMTP exception does not make `deliver_now` asynchronous or stop the request from waiting. The check claimed the action completes immediately, which the supplied code does not establish. The draft's claim about affecting all users was overstated, but this rejection does not demonstrate sound reasoning.

The working conclusion is that the app mechanics are ready for trials, while this local model's coaching judgement is not yet validated. Both raw drafts and rejection reasons are retained. Do not treat the filtered result as proof that no worthwhile conversation exists. A worthwhile next experiment is to compare a stronger model on these same saved evidence packets, rather than keep adding rules for these particular PRs.

The last cached draft took about 44 seconds to generate. Cold runs on the larger PR took several minutes; the second check adds another model call. These are observations from this machine, not a benchmark.

## Replay

Results are in the local `results/` directory, which is excluded from Git because each result includes source excerpts.

```sh
./qq --open results/pr1.json
./qq --open results/pr11-first.json
./qq --open results/pr11-checked.json
```

The unchecked draft is retained as `results/pr11-draft.json` for diagnosis. It contains unsupported advice and is not the recommended replay.

Use `n` and `p` to compare points, and Tab to move between the conversation, evidence, diff and context views.

## What has been verified

Twenty-one automated checks pass. They cover valid abstention, missing context, the two-point limit, exact citations, model failure handling, historical source reads, preserving uncommitted files, and sensitive-path exclusions. A real pseudo-terminal test covers navigation, rating persistence, resizing and quitting.

The TUI was also opened manually through a terminal for the real no-feedback and needs-context results. A clearly labelled synthetic finding was used to check the positive-point and source-evidence views. That synthetic finding is not counted as a successful model result.

## What remains to prove

The model should identify a discussion worth having, explain it accurately, and avoid unnecessary advice about scaling or architecture. Exact citations alone cannot establish those qualities. Local model latency is also substantial on larger PRs.

The cases in `examples/commonbound.json` include PR #12 for a later evaluation. It has not been run through the model yet.
