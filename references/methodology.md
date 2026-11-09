# Why the layouts look like this

Read this only if you need to justify a choice. The short version: use a shallow, numbered, date-first system, and only add structure that earns its place.

## Sources behind the design

| Idea | Used for | Source |
|---|---|---|
| **PARA** (Projects, Areas, Resources, Archive) | the `10/20/30/90` top-level split in Perfect mode | Tiago Forte, [Building a Second Brain](https://www.buildingasecondbrain.com/) |
| **Johnny.Decimal** numbering | numeric prefixes so folder order never shuffles | [johnnydecimal.com](https://johnnydecimal.com/) |
| **ISO 8601 dates** (`YYYY-MM-DD`) first in file names | names sort chronologically in every OS | [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601), [Johnny.Decimal forum on filenames](https://forum.johnnydecimal.com/t/the-recomended-structure-for-filenames-in-jd/1376) |
| Avoid special characters and spaces, keep names short and consistent | kebab-case, stripped `<>:"/\|?*` | [NIST electronic file organization tips (PDF)](https://www.nist.gov/document/electronicfileorganizationtips-2016-03pdf) |
| Shallow trees, no empty scaffolding ("Misc", "New Folder (2)") | max 3-4 levels, folders created only when a file needs them | [FileLocator folder-structure guide](https://filelocator-net.pages.dev/guides/organize-files-folder-structure/) |
| Skill authoring: concise, strong trigger description, progressive disclosure | the shape of `SKILL.md` | [Anthropic skill authoring best practices](https://claudeskills.info/blog/agent-skills-best-practices/) |

## Decisions and their reasons

- **Two modes, because there are two failure styles.** Pile-makers need a low-friction fix they will actually keep; maze-makers want a system they can trust. One layout cannot serve both. Quick mode never renames anything, so there is nothing to second-guess. Perfect mode renames because consistent names are the whole point.
- **Numbered top folders (`00`..`99`).** Alphabetical order scatters folders; numbers pin them. Gaps (`10`, `20`, `30`) leave room to add areas later without renumbering.
- **Date folders only for media.** Photos and screenshots are found by *when*; documents are found by *what*. Archive uses year folders because "older than a year" is the one date question documents get asked.
- **Context folder preserved when digging (`--depth > 1`).** A folder called "Semester 3" is information. Flattening it into `Documents/` would destroy that. The script keeps the first-level folder name unless `--flatten` is passed.
- **Review folders instead of deletion.** Duplicate detection is exact (size, first 64 KB, SHA-256), but the human still decides what to delete. Deletion is the one action that cannot be undone, so the tool never does it.
- **Project folders are atomic.** Moving a file out of a git repo or `node_modules` project breaks builds silently.
- **A Chaos Score at all.** A before/after number gives the user feedback that the effort worked, which is what makes a tidy system get repeated.
- **Retroactive perfection is a trap.** A forward-looking convention (`_Inbox` plus a weekly sweep) beats a perfect one-off cleanup that rots in a month.

## Chaos Score formula

`score = 100 x (0.30 pile + 0.15 dupes + 0.20 names + 0.15 maze + 0.10 stale + 0.10 junk)`, each term capped at 1.

- **pile**: loose files in the root / 25
- **dupes**: exact-duplicate files as a share of all files, x5
- **names**: files with copy markers, `(1)` counters, "final-final", placeholders, odd characters
- **maze**: empty + one-file + deeper-than-4 folders as a share of folders
- **stale**: loose files untouched for over a year
- **junk**: temp files, zero-byte files, `~$` lock files / 10

Verdict: pile-style if `0.7 pile + 0.3 stale` beats `0.6 maze + 0.4 names`, otherwise maze-style; under 15 is "already tidy".
