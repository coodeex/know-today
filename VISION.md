# Know Today — Vision

## Purpose

Know Today is an AI-assisted intelligence and learning project for staying current without having to manually scan a long list of feeds. It gathers information from chosen sources, identifies what matters, and turns it into clear, useful artifacts that can be reviewed quickly.

The intended result is a small collection of attractive, interactive HTML pages: daily or topic-focused briefings that make it easy to understand what happened, why it matters, and what to explore next.

## Information sources

The project should support a growing set of sources, beginning with:

- **Selected YouTube creators.** Follow chosen channels, discover new videos, obtain transcripts where available, and extract the main ideas, claims, demonstrations, recommendations, and learning points.
- **Newsletter subscriptions.** Give the system access to a dedicated inbox and let it read relevant newsletters. Extract useful editorial content while excluding sponsored sections, advertisements, affiliate promotions, and other paid placements.
- **Trending GitHub repositories.** Track notable projects and weekly star growth, including repositories surfaced through [Star History](https://www.star-history.com/) or its newsletter. Explain what each project does, why it is gaining attention, and whether it is relevant to the reader.
- **Additional sources and dynamic research goals.** Add specific feeds, sites, creators, or short-lived questions over time. The system should be able to investigate a goal such as “what is changing in this area?” and collect, compare, and analyze the relevant information.

Source selection should be explicit and easy to evolve. The aim is not to ingest everything; it is to build a high-signal view from trusted, relevant inputs.

## Analysis and artifact creation

After data is fetched, it should be passed to an AI agent for analysis. The agent should:

1. Separate meaningful information from noise, repetition, and sponsorship.
2. Summarize the important developments accurately, with source links and appropriate context.
3. Connect related items across sources, highlight trends, disagreements, and emerging themes, and explain why they may matter.
4. Extract practical learnings, recommended follow-ups, and questions worth watching.
5. Produce a polished, easy-to-scan HTML visualization rather than a plain text dump.

The HTML output should favor good information design: concise summaries, visual hierarchy, source attribution, interactive expansion for details, and lightweight charts or comparisons when they improve understanding. It should feel like a useful personal briefing or learning artifact, not a raw aggregation feed.

## Publishing model

Each generated artifact becomes a new dated page in a Git repository. A daily briefing, for example, should use the current-day timestamp in its filename or path so that the published history remains clear and browsable.

The agent should add the page to the repository, commit it with an intentional message, and push it to GitHub for version control and publication. The repository itself is the source of truth and the archive of past briefings.

No database, CMS, or separate content platform should be used. Source configuration, prompts, instructions, generated pages, and any lightweight state that is genuinely needed should live as files in the repository.

## Automation approach

A scheduled AI job should run the workflow. It can use Codex or a similar capable coding agent as the orchestrator, guided by clear Markdown instruction files stored in the repository.

The workflow should be designed as a transparent sequence:

1. Read the repository’s instructions and source configuration.
2. Fetch new material from configured sources.
3. Use small, purpose-built scripts for capabilities that require them, such as reading the dedicated newsletter inbox or obtaining video transcripts.
4. Provide the collected material to the AI agent for analysis and editorial decisions.
5. Create the dated HTML briefing page and any supporting static assets.
6. Validate the generated output, then commit and push it to GitHub.

The special scripts should collect and normalize data, while the AI agent should make the higher-level decisions: assessing relevance, filtering sponsorship, synthesizing evidence, shaping the narrative, and implementing the final HTML artifact. This keeps the system flexible as sources and goals change, while keeping its operating instructions understandable and version-controlled.

## Guiding principles

- Optimize for signal, clarity, and practical learning rather than volume.
- Preserve source links and distinguish source facts from the AI’s interpretation.
- Treat sponsorship and promotional material as noise unless it is explicitly relevant.
- Make each page useful in a few minutes, with deeper detail available on demand.
- Keep the system simple, file-based, inspectable, and reproducible through Git.
- Allow the project to expand from recurring daily briefings into targeted research and discovery tasks.
