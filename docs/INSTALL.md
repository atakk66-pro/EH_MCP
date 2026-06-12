# Installing the Employment Hero extension

Two parts: the maintainer builds and distributes one file; each director
installs it and connects once.

## For the maintainer (one-time build)

You need Node.js (for the packaging CLI). Everything else (Python, dependencies)
is handled by Claude Desktop at install time via the `uv` runtime.

```bash
cd "Project for EH Noblecare"
npx -y @anthropic-ai/mcpb validate manifest.json   # optional sanity check
# name it after the manifest.json version (currently 0.4.4):
npx -y @anthropic-ai/mcpb pack . "employment-hero-readonly-0.4.4.mcpb"
```

(Pass the output filename explicitly: without it, `mcpb pack .` names the file
after the directory.) Better still: push a `v0.4.4` tag and let
`.github/workflows/release.yml` build and publish a checksummed `.mcpb` on the
Releases page.

Send the `.mcpb` (the latest from the Releases page) to each director by email
or shared drive. It contains no secrets; the Client ID/Secret are entered
per-person at install time.

Before anyone installs, make sure the Employment Hero app exists:
- An EH plan with API access (**Platinum or above**).
- A registered app in the [Developer Portal](https://developer.employmenthero.com/)
  with the read-only scopes ticked and the redirect URI
  `https://127.0.0.1:8765/callback` (Employment Hero requires https). You get one
  **Client ID** and **Client Secret** to share.

## For each director (install + connect)

1. Open Claude Desktop. Go to **Settings > Extensions**.
2. Under **Advanced / Extension Developer**, choose **Install Extension...** and
   pick the `the latest employment-hero-readonly .mcpb` file you were sent.
3. In the install dialog, paste the **Client ID** and **Client Secret** you were
   given, and the **Organisation ID** if you were given one (it lets everything
   work without an extra lookup). Leave the other fields at their defaults. The
   credentials are stored in your computer's keychain, not in a file.
4. In a chat, type: **connect Employment Hero**. Claude replies with a sign-in
   **link**.
5. **Click the link**, sign in as an administrator, and approve access.
6. Your browser then tries to open a `127.0.0.1` page that **fails to load**
   ("can't reach this site"). That is expected. **Copy the full web address**
   from that page's address bar (it contains `code=`).
7. Paste it back to Claude: **complete the Employment Hero sign-in with** <the
   address you copied>. Claude confirms you are connected. You will not need to
   do this again on this computer.
8. Ask for what you need, for example: "List our work locations" or "How many
   employees do we have?".

This sign-in deliberately uses no local server, so corporate networks,
firewalls, and certificate policies do not interfere.

## If something goes wrong

- **"Not connected" message**: say "connect Employment Hero" and complete the
  browser step.
- **The browser did not open**: wait for the connect step to time out (a few
  minutes); its message includes the sign-in link to open manually.
  (Maintainers: the URL is also logged immediately in the extension logs under
  Settings > Extensions > the server's logs.)
- **Sign-in listener / port error**: something else is using port 8765. Close it
  and connect again, or set a different "Sign-in callback port" in the
  extension settings and register that port's redirect URI on the EH app.
- **403 / access denied**: the EH plan may lack API access (needs Platinum), or
  the admin who authorized lacks permission for that data. Almost every scope
  needs an EH **administrator** to do the connect step.
- **Install blocked / Python error**: the `uv` runtime download may have failed
  (rare, seen on some ARM machines). Installing `uv` system-wide first resolves
  it: `brew install uv` (macOS) or `winget install astral-sh.uv` (Windows).

## What it can and cannot see

Read-only, and only aggregate, non-personal data leaves your machine to Claude:
organisation/team/location lists and headcounts. No names, contact details, pay,
or other personal fields are ever returned. See
[KPI_ROADMAP.md](KPI_ROADMAP.md) for the planned KPI tools.
