# Publishing the Confluence page

Two files here are the same guide in two formats:

| File | Use |
|---|---|
| `start-stack-app-guide.md` | Readable source / review copy (renders on GitHub). |
| `start-stack-app-guide.storage.xhtml` | Confluence **storage format** — what the page body actually is. |

## Steps

1. Create a new page in the target space (e.g. under the team's *Tools* parent).
2. Attach the six videos from `docs/videos/` to the page **first**
   (`⋯ → Attachments → upload`). The page body references them by file name
   via the `multimedia` macro, so the attachments must exist.
3. Insert the body. Two ways:
   - **Editor:** `⋯ → Insert → Markup`, choose *Confluence storage format*, paste
     the contents of `start-stack-app-guide.storage.xhtml`, Insert, Publish.
   - **REST API** (no editor clicking):
     ```bash
     export CONFLUENCE_BASE=https://appliedint-frontier.atlassian.net/wiki
     export CONFLUENCE_USER=you@example.com
     export CONFLUENCE_TOKEN=<api token>   # id.atlassian.com → Security → API tokens
     python3 docs/confluence/publish.py --page-id 738885634        # replaces the page body
     python3 docs/confluence/publish.py --page-id 738885634 --append   # keeps existing content
     ```
     `--page-id` puts the guide on that exact page (space IF);
     `--append` adds it below whatever the page already holds. Without
     `--page-id`, the script creates/updates by title in `--space TEAM`.
     It also uploads the videos from `docs/videos/` as attachments.

     Note: if the page is a brand-new never-published draft, click
     **Publish** on it once (empty is fine) so the REST API can see it,
     then run the script.
4. Check the videos play inline; Confluence Cloud plays `.mp4` attachments
   natively.

## Keeping it current

The page's text mirrors `README.md`; the videos are regenerated with
`./venv/bin/python tools/make_videos.py`. After a UI change: regenerate,
re-upload the changed `.mp4`s (same names — the macro references survive),
and re-paste the body if the text changed.
