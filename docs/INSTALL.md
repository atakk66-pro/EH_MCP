# Installing the Employment Hero extension

Two parts: the maintainer builds and distributes one file; each director
installs it and connects once.

## For the maintainer (one-time build)

You need Node.js (for the packaging CLI). Everything else (Python, dependencies)
is handled by Claude Desktop at install time via the `uv` runtime.

```bash
cd "Project for EH Noblecare"
npx -y @anthropic-ai/mcpb validate manifest.json   # optional sanity check
npx -y @anthropic-ai/mcpb pack . employment-hero-readonly-0.1.0.mcpb
```

(Pass the output filename explicitly: without it, `mcpb pack .` names the file
after the directory.)

Send `employment-hero-readonly-0.1.0.mcpb` (the version number is in the
filename) to each director (email, shared drive, or attach it to a GitHub
release). It contains no secrets; the Client ID/Secret are entered per-person at
install time.

Before anyone installs, make sure the Employment Hero app exists:
- An EH plan with API access (**Platinum or above**).
- A registered app in the [Developer Portal](https://developer.employmenthero.com/)
  with the read-only scopes ticked and the redirect URI
  `https://127.0.0.1:8765/callback` (Employment Hero requires https). You get one
  **Client ID** and **Client Secret** to share.

## For each director (install + connect)

1. Open Claude Desktop. Go to **Settings > Extensions**.
2. Under **Advanced / Extension Developer**, choose **Install Extension...** and
   pick the `employment-hero-readonly-0.1.0.mcpb` file you were sent.
3. In the install dialog, paste the **Client ID** and **Client Secret** you were
   given, and the **Organisation ID** if you were given one (it lets everything
   work without an extra lookup). Leave the other fields at their defaults. The
   credentials are stored in your computer's keychain, not in a file.
4. In a chat, type: **connect Employment Hero**.
5. Your browser opens to the Employment Hero sign-in. Approve access.
   - After you approve, the browser may show a **"your connection is not
     private"** warning on a `127.0.0.1` address. This is expected and safe: the
     page is on your own computer. Click **Advanced**, then **Proceed to
     127.0.0.1**. (It appears because the local sign-in step uses a certificate
     made on your machine rather than a public website's.)
   - When the tab says sign-in is complete, you are done. You will not need to
     do this again on this computer.
6. Ask for what you need, for example: "List our work locations" or "How many
   employees do we have?".

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
