# CopperPilot — GitHub Public Release Steps

**Date:** February 15, 2026
**Status:** Ready for release after completing the steps below

---

## What's Already Done

- [x] Professional README.md (root)
- [x] MIT LICENSE with correct attribution
- [x] .env.example with placeholder instructions
- [x] .env contains ONLY placeholders (no real keys)
- [x] .gitignore covers all sensitive directories
- [x] All docs cleaned of internal fix series labels and run IDs
- [x] Hardcoded paths removed from source code
- [x] test_kicad_compatibility.py uses dynamic path discovery
- [x] CopperPilot_PublicRelease_Prompt.md removed
- [x] setup.sh and start_server.sh present and working
- [x] requirements.txt complete with pinned versions

---

## Step 1: Fix Remaining Issues (5 minutes)

### 1a. Update pyproject.toml URLs

Three URLs have `<your-org>` placeholder:

```
# Line 25-27 — change to:
Homepage = "https://github.com/zivelo1/CopperPilot"
Documentation = "https://github.com/zivelo1/CopperPilot/tree/main/docs"
Issues = "https://github.com/zivelo1/CopperPilot/issues"
```

### 1b. Add to .gitignore

Add these lines to prevent internal files and stale backups from being committed:

```
# Internal development notes
docs/Internal/

# Timestamped backup files at root level
*.pre-freerouting-*
kicad_converter.py.20*

# Claude plans
.claude/plans/
```

### 1c. Decide: docs/QUALITY_BASELINE.md

This file contains internal fix series labels, run IDs, and forensic analysis. Options:
- **Option A (recommended):** Add `docs/QUALITY_BASELINE.md` to `.gitignore` — keep locally, don't publish
- **Option B:** Leave it in — some readers may find the quality tracking interesting
- **Option C:** Move to `docs/Internal/` (already excluded by step 1b)

---

## Step 2: Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `CopperPilot`
3. Description: `AI-powered PCB design from natural language`
4. Visibility: **Private** (start private, make public after verification)
5. Do NOT initialize with README, .gitignore, or license (we have all of these)
6. Create repository

---

## Step 3: Initialize Git and Push

```bash
cd /path/to/CopperPilot

# Initialize git (if not already)
git init

# Verify .gitignore is working — this should show NO sensitive files
git status

# CHECK CAREFULLY: The following should NOT appear in git status:
#   .env (only .env.example should appear)
#   Backup/
#   output/ contents (only output/.gitkeep)
#   logs/ contents (only logs/.gitkeep)
#   storage/
#   venv/
#   .claude/settings.local.json
#   .digikey_token.json
#   docs/Internal/
#   __pycache__/ directories

# If anything sensitive shows up, STOP and fix .gitignore first

# Stage all files
git add .

# Review what's staged — LAST CHANCE to catch sensitive files
git diff --cached --name-only | head -100

# Commit
git commit -m "Initial public release of CopperPilot"

# Connect to GitHub
git remote add origin https://github.com/zivelo1/CopperPilot.git
git branch -M main

# Push (still private at this point)
git push -u origin main
```

---

## Step 4: Verify on GitHub (Private Repo)

Before making public, check the repo on GitHub:

### Security Check
- [ ] No `.env` file visible (only `.env.example`)
- [ ] No `Backup/` directory visible
- [ ] No `storage/` directory visible
- [ ] No `venv/` directory visible
- [ ] No `__pycache__/` directories visible
- [ ] No `.digikey_token.json` visible
- [ ] No `.claude/settings.local.json` visible
- [ ] No `docs/Internal/` visible
- [ ] Search repo for API key prefixes — zero results
- [ ] Search repo for hardcoded local paths — zero results

### Content Check
- [ ] README.md renders correctly with proper formatting
- [ ] Architecture diagram displays properly
- [ ] All documentation links work (docs/*.md files exist)
- [ ] LICENSE file is visible and correct
- [ ] .env.example has only placeholders
- [ ] setup.sh and start_server.sh are present
- [ ] requirements.txt is present
- [ ] Frontend files are present (frontend/)
- [ ] Test files are present (tests/)

---

## Step 5: Make Repository Public

1. Go to repository Settings > General
2. Scroll to "Danger Zone"
3. Click "Change visibility" > Make public
4. Confirm

---

## Step 6: Post-Release (After Making Public)

### Rotate ALL API Keys

These keys have been visible in local files and conversation history. Rotate them NOW:

| Service | Where to Rotate |
|---------|----------------|
| Anthropic | https://console.anthropic.com/settings/keys |
| Mouser | Mouser developer portal |
| DigiKey | DigiKey developer portal (Client ID + Secret) |

After rotating, update your LOCAL `.env` file with the new keys (the file is gitignored, so this won't affect the repo).

### Optional Enhancements
- Add a GitHub topic/tags: `ai`, `pcb-design`, `circuit-design`, `kicad`, `eda`, `claude`
- Add a short "About" description on the repo page
- Pin the repository on your GitHub profile
- Share on LinkedIn with a brief write-up

---

## Files That Will Be Published

Here's what WILL be in the public repo (everything NOT in .gitignore):

```
CopperPilot/
├── .env.example              # Placeholder config template
├── .gitignore                # Exclusion rules
├── LICENSE                   # MIT License
├── README.md                 # Professional README
├── pyproject.toml            # Python project config
├── requirements.txt          # Pinned dependencies
├── setup.sh                  # Setup script
├── start_server.sh           # Server launcher
├── server/                   # FastAPI server + config
├── workflow/                 # 7-step pipeline + agents
├── ai_agents/                # AI agent manager + prompts
├── scripts/                  # Format converters (KiCad, Eagle, EasyEDA, SPICE, BOM, Schematics)
├── frontend/                 # Web interface
├── tests/                    # Test suite
├── data/                     # Component ratings database
├── utils/                    # Utility modules
├── docs/                     # Documentation (minus Internal/)
│   ├── PROJECT_OVERVIEW.md
│   ├── CHANGELOG.md
│   ├── TESTING_GUIDE.md
│   ├── KICAD_CONVERTER.md
│   ├── SPICE_CONVERTER.md
│   ├── EAGLE_CONVERTER.md
│   ├── EASYEDA_PRO_CONVERTER.md
│   ├── DUAL_SUPPLIER_BOM_SYSTEM.md
│   ├── AI_MODEL_CONFIGURATION.md
│   ├── BOM_CONVERTER.md
│   ├── SCHEMATICS_CONVERTER.md
│   ├── README.md
│   ├── Screenshots/
│   └── Test Prompts Examples/
├── output/.gitkeep           # Empty output directory
└── logs/.gitkeep             # Empty logs directory
```

## Files That Will NOT Be Published

These are blocked by `.gitignore`:

```
.env                          # Real API keys (placeholders now, but still excluded)
.digikey_token.json           # OAuth token
.claude/settings.local.json   # Claude Code history (contains key fragments)
Backup/                       # 386 MB of archived backups (contain old credentials)
storage/                      # 126 MB of runtime session logs
output/*/                     # 31 MB of generated circuit outputs
logs/*/                       # 38 MB of runtime logs
venv/                         # 390 MB Python virtual environment
__pycache__/                  # Python bytecode cache (19 directories)
.DS_Store                     # macOS metadata (29 files)
.pytest_cache/                # Test cache
docs/Internal/                # Internal TODO lists (41 KB)
```
