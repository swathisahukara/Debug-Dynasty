# Demo video script (target 3:30, limit 4:00)

Record the browser at http://127.0.0.1:8765 with the terminal visible for one beat. Start `python3 -m app.server` before recording. Run the agent loop once beforehand so Nightshift is warm, and keep a spare take of that step because Nemotron takes 30 to 90 seconds (cut or speed up the wait, keep the trace visible).

| Time | On screen | Say |
|---|---|---|
| 0:00 | Title slide, then the Investigate tab | "npm supply-chain attacks like ua-parser-js and event-stream leave traces in release metadata. Package Trail turns those traces into risk indicators with cited evidence. Not accusations." |
| 0:15 | Click **ua-parser-js**, Replay, Investigate | "First, replay. This answers in milliseconds with zero LLM calls: MEDIUM, from a compiled rule, citing the exact package@version rows." Point at the cited rows and the free-cost meter. |
| 0:40 | Same case, **Agent loop**, Investigate | "Now the part that built that rule: an agent loop on Nemotron through Meterless Nightshift. A Skeptic looks for benign explanations, an Evaluator that is not an LLM checks every cited row exists, a Reporter writes the verdict." Show the live trace and, if one happens, an Evaluator rejection and retry. |
| 1:30 | Verdict card and cost meter | "Two model calls, a fraction of a cent. The facts the Skeptic saw are deterministic: for example whether every release line in a burst already existed." |
| 1:45 | **Compiled graph** tab | "The reasoning is compiled into this editable graph: Zetaris query nodes, indicator nodes, a rule table." Change one rule to high, return to Investigate, replay, show the verdict changed. Set it back. |
| 2:10 | Switch data source to **Zetaris**, replay | "Same question against live Zetaris Lightning SQL over REST tables and views. Same verdict." |
| 2:25 | **Fleet heatmap** tab | "And because replay is free, here is every package at every date: 4,524 questions answered in about five seconds, zero model calls. The bright cells are the incidents." Click one flagged cell to jump to its evidence. |
| 2:45 | Investigate, tick **live npm registry**, type a popular package (for example `lodash`), Investigate | "This is not a fixed dataset. The same graph runs on any public npm package, straight from the registry." Point at the LOW verdict and the note about removed versions. |
| 3:00 | Click **Copy link** | "Every result has a permalink and a Markdown report, so a verdict can be shared and re-run." |
| 3:05 | **Scoreboard** tab | "On 40 cases: same detection as single-shot, one false alarm instead of ten, every cited row real, about a fifth of the cost. Over 4,524 package-date cells, single-shot would cost about ten dollars, the agent about twenty-two cents, compiled replay zero." |
| 3:20 | Honest limits slide or the README limits | "Detection is capped at five of ten because five incidents leave no metadata trace, and some rules were tuned after seeing results. All declared in the README." |
| 3:30 | Close slide | "Compile once, replay for free. Thank you Zetaris, Meterless, NVIDIA and Cursor." |

Must be visible in the video: Zetaris query running, a Meterless call (Nightshift endpoint and the H-MEM engine), Nemotron, the passing tests (show `python3 -m unittest discover -s tests` for two seconds) and the repo URL.
