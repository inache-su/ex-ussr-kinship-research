# ex-USSR Kinship Research

![ex-USSR Kinship Research cover](docs/cover.jpg)

**An evidence-first genealogy skill for AI agents (Codex, Claude Code and other Agent Skills runtimes).** It turns an agent into a careful family-history researcher for the former USSR, the Soviet Union and the Russian Empire. The agent reads church books and civil records, military, deportation and repression files, and unindexed archive scans. It keeps every find traceable, separates records from interpretation and says plainly what is proven and what is not.

Coverage includes all 15 former Soviet republics: Russia, Ukraine, Belarus, Moldova, Estonia, Latvia, Lithuania, Georgia, Armenia, Azerbaijan, Kazakhstan, Kyrgyzstan, Tajikistan, Turkmenistan and Uzbekistan. Archives are chosen by the event's historical jurisdiction and current record custodian; a regional example does not replace local research.

The skill's instructions are written in Russian, but **the agent talks to you in your language**: English, Ukrainian, Russian, Polish, German and so on. It quotes sources in their original spelling with a translation, and builds search queries in the languages of the records.

## About this fork

This repository, maintained by [inache-su](https://github.com/inache-su), is a fork of [DenisSergeevitch/ex-ussr-kinship-research](https://github.com/DenisSergeevitch/ex-ussr-kinship-research). It changes the original skill in three ways:

- **Living relatives search.** The agent searches VK, Odnoklassniki, Facebook and memorial pages kept by descendants. It drafts first messages and sends them only on your instruction. The search runs by default; set `scope.modern_relatives_search: false` in the case intake to turn it off. See the [guidance](references/living-relatives-search.md).
- **Research until you stop it.** The answer to your original question is an interim result. When one branch is exhausted, the agent moves on to earlier generations, ancestors' siblings and their descendants, spouses' lines and living relatives. It stops when you tell it to, at an environment limit, or when every remaining step waits for you or an outside reply.
- **Case tooling from real use.** Each case gets a research-state plan, and `build_tree.py` renders the registers as an HTML family tree. The audit checks the search log, field values and relationships missing from the report, and a folder can be hashed into a `SHA256SUMS` manifest. When one target stops producing records, a per-target search budget turns it into an institutional request or moves research to the next branch.

The fork's changes are listed under "Unreleased" in the [changelog](references/changelog.md). The skill checks this fork for updates, not the original repository.

---

## What it does

- **Case intake and scope.** One research question, known facts, who may be alive, what is off-limits.
- **Reproducible registers.** Persons, artifacts, claims, relationships and a full search log (CSV), plus a final report template.
- **Historical jurisdiction model.** It resolves every event to the state, province, district, parish or civil registry *as of the event date*, not today's map.
- **Name-variant matrices.** Pre-reform Russian, Ukrainian, Polish, Romanian, German and Yiddish forms, patronymics, maiden names and transliterations.
- **Source strategy.** Originals first, then official catalogs, indexes, published document collections, and only then trees and forums as leads.
- **Evidence protocol.** Claims get explainable statuses, not percentages: `hypothesis`, `single-source`, `corroborated`, `strongly-corroborated`, `contradicted`, `unresolved`. Copies and mirrors of one record share an `independence_group`, so they never count as independent proof.
- **Identity resolution.** Namesakes stay separate `person_id`s until distinguishing evidence appears: house number, parents, godparents, exact birth date or military unit.
- **Audit script.** It checks referential integrity and flags weak corroboration before you write conclusions. An independence group counts only when a cited artifact belongs to it, so corroboration cannot be declared into existence. It also checks the final report: every cited ID must exist in the registers and every status must match them. A summary shows what is still uncorroborated or marked illegible.
- **Institutional requests.** Draft and, when authorized, send focused requests to archives, libraries, universities and museums using available email or official web tools. If needed, offer a supported mail integration or a ready-to-send letter. Record the outcome, avoid duplicate sends and treat replies as evidence. See [correspondence guidance](references/correspondence.md).
- **Final report.** Every relationship is laid out edge by edge, with contradictions, failed searches and concrete next steps.
- **Targeted indexed-record research.** Find relevant FamilySearch books by place or DGS through an existing lawful browser session, view specific records, and retain only evidence fragments permitted by the source. Local helpers search relatives, witnesses and name variants in saved fragments, preserving their context and file checksums. [Workflow and coverage limits](references/familysearch-indexes.md).
- **Living relatives search.** Along researched family lines, the agent looks for living relatives on VK, Odnoklassniki, Facebook and memorial pages kept by descendants. When a network needs sign-in, it opens the login page in its browser and you sign in. It records a profile as a candidate only when a case detail besides the surname matches, such as an ancestor in their posts or a known relative, and the kinship stays a hypothesis until records confirm it. The agent drafts a first message and sends nothing without your instruction. [Guidance](references/living-relatives-search.md).
- **WWI source search.** Search GWAR reports, hospital and award records by person or locality, then locate the source image. [Workflow](references/ww1-search.md). Both helpers feed the existing artifact register and search log; they do not establish identities or kinship automatically.

Release history: [changelog](references/changelog.md).

## Install

Clone the repository into your agent's skills folder:

```bash
# Codex
git clone https://github.com/inache-su/ex-ussr-kinship-research ~/.codex/skills/ex-ussr-kinship-research

# Claude Code (personal skills)
git clone https://github.com/inache-su/ex-ussr-kinship-research ~/.claude/skills/ex-ussr-kinship-research
```

For a single project, put the folder in `.claude/skills/` inside the repository. The scripts need only Python 3 and the standard library; `build_pdf.py` also needs a Chromium-based browser.

## Use

Describe the family question. The agent works from available information and continues while questions or access requests await a reply. After the first answer it keeps researching until you stop it; the other end conditions are listed in [About this fork](#about-this-fork). For example:

- *"My great-grandfather was exiled to Kazakhstan in the 1930s. Help me find his parents in church records."*
- *"Here are scans of a marriage certificate and a soldier card. Check whether they are the same person and build the evidence chain."*
- *"Find the parish and the right FamilySearch film for a village in Podolia in the 1890s and read the births for the surname X."*

Keep private case data outside the skill's Git checkout. From the skill folder:

```bash
python scripts/init_case.py --case-dir ~/kinship-cases/my-case --research-question "Who were Maria's parents?" --subject-label "Maria"
python scripts/hash_artifact.py ~/kinship-cases/my-case/scans/marriage-1902.jpg   # SHA-256 for every saved artifact
python scripts/audit_evidence.py --case-dir ~/kinship-cases/my-case             # check registers before the final report
python scripts/build_tree.py --case-dir ~/kinship-cases/my-case                # interactive HTML family map
python scripts/build_tree.py --case-dir ~/kinship-cases/my-case --shared       # map with living people's details hidden
python scripts/build_pdf.py --html ~/kinship-cases/my-case/pdf-source/report.html --out ~/kinship-cases/my-case/report.pdf
```

`init_case.py` refuses to create a case inside the skill folder, including with
`--force`. Git ignores common legacy case-folder names as an additional safeguard;
check staged files before contributing, especially if moving an existing case.

`build_pdf.py` needs Chrome, Chromium or Edge installed (or `CHROME_PATH`). With `--png-dir` it also renders pages to PNG for review if `pypdfium2` is available.

Use static HTML with local or embedded images. Active HTML and network image sources are rejected; source links remain clickable. A failed render preserves any existing output PDF.

## HTML family map

`build_tree.py` uses the atlas template from the Genes project, bundled in `assets/family-tree/`. It creates one offline HTML file with embedded styles, scripts and fonts. Open `tree.html` directly in a browser; no web server or package installation is needed. Use `--out /path/to/map.html` to choose another output file.

The map has name and alias search, person and relationship cards, zoom and panning, ancestor and descendant views, and a kinship path finder. Its download menu exports the map as SVG or its data as JSON. Cards include notes, claims and source references from the case registers. Positions and group selectors are generated from those registers.

Candidates keep separate IDs. Hypotheses use dashed lines, people without active links have their own section, and contradicted relationships appear only in cards. Possible identity matches, godparents and relationships of unknown degree are excluded from kinship paths. The map preserves the registers and must be rebuilt after they change.

`--shared` creates `tree-shared.html`. Living and potentially living people appear as initials without dates or aliases. All free-text biographies, relationship notes, source titles and source locations are withheld, including text in deceased people's cards that could name living relatives. Register IDs and the relationship structure remain in the shared file and its exports.

## Repository layout

```
SKILL.md                         main instructions (workflow, hard rules, language policy)
references/
  source-strategy.md             source hierarchy, query patterns, catalogs, archive requests
  correspondence.md              recipients, mail integration, authorized sending and replies
  evidence-protocol.md           artifact assessment, statuses, identity resolution, conflicts
  ex-ussr-locale-guide.md        jurisdictions, name variants, calendars, record types by period
  browser-and-captcha.md         browsing, sign-in, one CAPTCHA attempt and hand-off, rate limits
  privacy-and-safety.md          living people, minors, DNA, sensitive findings
  living-relatives-search.md     living relatives on social networks: sign-in, routes, candidates, contact
  seed-sources.md                curated starting resources with reliability classes
  field-lessons.md               practical lessons from a real case
  changelog.md                   release history
  photo-search.md                finding, identifying, dating and storing photos
  habsburg-galicia-bukovina.md   Galicia and Bukovina under the Habsburgs and after
  familysearch-indexes.md       targeted browser research, permitted local snapshots and coverage
  ww1-search.md                 GWAR WWI person/locality search and source-image locators
assets/                          case intake, CSV registers, research-state plan, final report template,
                                 family-tree/ (HTML atlas template, UI strings, scripts, styles and licensed fonts),
                                 photos README template, readable PDF template (report-pdf.template.html)
scripts/                         init_case.py, hash_artifact.py, audit_evidence.py, build_pdf.py, build_tree.py
                                 familysearch.py, gwar.py, register_search.py and shared local analysis modules
evals/discovery-and-logic.yaml   trigger and reasoning test cases
tests/                           unit tests (python3 -m unittest discover -s tests)
```

## Responsible use

- **Family history, not surveillance.** The skill searches for living relatives, including on social networks, but it does not use leaked databases, people-search brokers or face recognition, does not look up minors and does not record phones, addresses or workplaces. Shared reports hide living people's data.
- **Access checks.** The agent may try an actual CAPTCHA once through normal controls in its internal browser when supported and allowed. If user action is needed, it opens the relevant tab when possible and provides the URL and required action; sign-ins are done by the user. No external solvers, protection bypass, paywall, geo-block or rate-limit evasion, or leaked databases. See [browser guidance](references/browser-and-captcha.md).
- **No uploads of your documents or DNA data** to third-party services without your explicit consent.
- **Sensitive findings** (deportation, repression, adoption, DNA surprises) are reported neutrally and only as far as the question requires.
- **Authorized correspondence.** The skill can send institutional requests through available tools when the user has authorized them; it does not ask again for an already authorized send. Connecting a mailbox alone does not authorize sending, attachments or paid services. Verify the current official contact and procedure, and keep credentials and private case correspondence outside the skill repository.

## Contributing

New sources are welcome in `references/seed-sources.md`. Record verified owner, jurisdiction, collection, provenance, IDs, access, restrictions and check date where known; mark gaps instead of guessing. Keep personal data out of examples.

Source-search helpers use Python's standard library and the existing case registers. Run `python3 -m unittest discover -s tests` to check local parsing, GWAR checkpoints, access failures, unresolved coverage and evidence registration against synthetic data. FamilySearch discovery and targeted viewing use the existing lawful browser session; its Python helpers analyze saved fragments. Keep private research files outside this checkout.

Run `node --test tests/test_tree_layout.cjs` for the diagram routing checks, including separate connector lanes and links across occupied rows. Node.js is used for these tests; generating an HTML map still requires only Python.

## License

[MIT](LICENSE) © 2026 Denis Shiryaev.

---

Original skill by Denis Shiryaev ([@DenisSergeevitch](https://github.com/DenisSergeevitch)). This fork is maintained by [inache-su](https://github.com/inache-su).
