# Agent Relay walkthrough

[Watch/download the video](../media/agent-relay-walkthrough.mp4) · [Visual guide](../media/relay-workflow.png)

A 66-second, silent, captioned slideshow using captures of the real dashboard UI. The README embeds a looping GIF so visitors can watch inline; the MP4 provides playback controls. All account readings, repository names, test results and ownership actions are simulated. No credentials, live provider requests or real ownership transfers are used. The demonstration explains the workflow; it is not evidence of an end-to-end production transfer.

## Transcript

| Time | What the walkthrough explains |
|---|---|
| 0:00–0:08 | **Your next session starts here.** Agent Relay keeps working context and the next action close at hand for developers using Claude Code, Codex, or both. |
| 0:08–0:18 | **Check capacity.** Compare recorded account readings before starting the next step. The example has Claude at 8% session capacity and Codex at 72% weekly capacity. These are different windows, not interchangeable budgets. Read freshness and reserve as well as percentages. |
| 0:18–0:28 | **Save context and verify state.** Record changes, reasoning, verification and unfinished work. Use `/handoff` then `/checkpoint` in Claude Code, or `$handoff` then `$checkpoint` in Codex. A checkpoint links continuation instructions to repository state. |
| 0:28–0:38 | **Release deliberately.** Stop the source session before releasing ownership. Relay checks participating workflows but cannot stop another IDE or prevent independent edits. Repository changes require a fresh release. |
| 0:38–0:48 | **Continue with a clear owner.** Choose the destination account, claim ownership and copy the resume prompt. Open the destination tool yourself and verify the checkpoint. Relay does not launch a model task or copy chat history. |
| 0:48–0:58 | **Check from your phone.** View quotas, workstreams and supported actions in a paired browser. HTTPS and pairing are required; the host must stay awake and reachable. This is for one owner and their devices. |
| 0:58–1:06 | **Start small.** Begin with handoffs and working rules. Add usage tracking and phone access as needed. From the kit checkout, run `bash install.sh --tool both /path/to/your/project`. See the main README for installation and `docs/remote-access.md` for phone setup. You control tools, reviews and final decisions. |

## Regenerate

Requirements: Python 3, Node/npm, Microsoft Edge and FFmpeg with libx264. These commands are run from the repository root. The Playwright CLI package may be downloaded by npm; provider services are not contacted by the demo.

Start the isolated, loopback-only static server in one terminal:

```sh
python docs/demo/serve.py
```

In another terminal:

```sh
npx --yes --package @playwright/cli playwright-cli -s=relay-video open about:blank --browser msedge
npx --yes --package @playwright/cli playwright-cli -s=relay-video run-code --filename docs/demo/capture-ui.js
npx --yes --package @playwright/cli playwright-cli -s=relay-video run-code --filename docs/demo/capture-frames.js
python docs/demo/export.py
npx --yes --package @playwright/cli playwright-cli -s=relay-video close
```

Pass `--ffmpeg C:/ffmpeg/bin/ffmpeg.exe` to the exporter if FFmpeg is not on PATH. Stop the static server with Ctrl+C when finished. No live Relay server is required.

`capture-ui.js` intercepts API requests with fixtures and captures the actual dashboard. `walkthrough.html` supplies the captions and layout. `capture-frames.js` saves seven 1280×720 frames under `output/playwright/` and the visual guide under `docs/media/`. `export.py` creates the H.264 MP4, a 960×540 looping GIF, and poster. The video has no audio track; all explanation is visible in the frames and available in the transcript above.
