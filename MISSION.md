<!-- What this project is actually for, in Oliver's words. Said 2026-10-03, transcribed and
     lightly tidied, nothing added. The idea's origin is IDEA.md; the plan is ROADMAP.md.
     When a decision here conflicts with a plan there, this file wins. -->

# MISSION.md — what JobMatch is for

## The brief (2026-10-03)

I want to start applying for jobs *now*.

I started this project when I was applying for jobs in January/February. The problem I had was
that **finding** the jobs was a repetitive action, and I don't think that's worth anyone's time.
There are multiple job sites, multiple offers online. My vision was to make this all fall into
one place. It should save people — or students — the time it takes to find a job. You are not
going to be *fishing* for a job; you are going to get it under your nose. So you have time to
build MVPs instead.

What it has to do:

- **Read your CV** and extract your skills, languages, location and so on, then match you
  against jobs by scraping the job sites.
- **Know when the job was published.** If you're job hunting you go on the site every day to
  see if something new popped up. Your first run looks at jobs that are one day old, two days,
  three — a week old at most. That has to be there.
- **Location is asymmetric.** If you're in Košice you can only take an on-site job in Košice,
  but you can take a remote job anywhere in the world. Keep that in mind.
- **Adjacent stacks count.** If you're a React developer you can also switch to another stack —
  Angular, say — if you're able to. A job in a neighbouring technology is not a miss.

## Scope, deliberately narrowed

**Don't build it for every single person right now. Make it work for me.** Not "as a website"
for an audience — as the thing that gets *me* matched. The multi-user machinery already exists
and should keep working, but nothing new gets built for a hypothetical user this week.

## The definition of done

> The end result of this project is me getting a job that I am happy with — a perfect match.

Not a feature list, not a test count, not a deploy. Those are only worth what they contribute
to that sentence. The score at the top of my list has to be a job I would actually take.

## The deadline

**This week.** By the end of it I want it deployed and working — matches arriving without me
going to look for them.

## Decisions (2026-10-03, asked and answered)

The brief above was narrowed in conversation the same day. Where the two differ, these win:

- **Profesia only.** Slovakia is the market; Profesia is the board people actually get hired
  through. The other six adapters still work and are switched off in the crawl, not deleted.
- **Košice or remote.** On-site anywhere else is out, Bratislava included — a job 400 km away is
  not a commute, and "see if you can work remotely for locations outside Košice" is the rule.
- **Nothing above junior.** Senior, lead, principal, architect and head-of titles are hidden
  outright rather than ranked low.
- **Internship, working student, remote contract or freelance** are the engagements being hunted
  — not full-time mid-level roles.
- **No email, no deploy, this week.** The matches are read on the web page, and the page runs on
  Oliver's Mac. The digest and the VPS were both offered and both declined for now.
- **The page is a list and nothing else.** Title, company, location, age, pay, score. The title
  goes to Profesia. One button records that he applied.

## The second brief (2026-10-04)

Said after the first real scan — 12 matches, three of them senior roles and several not
programming jobs at all. Transcribed and lightly tidied, nothing added.

**Why this project happened.** When I started applying in January/February I was only
applying through Profesia. What was really time consuming was finding the *correct* job.
In this day and age there are multiple tools, and I want to spend more time getting ready
for the job — so I want to pick the jobs that have the highest match with me.

**The things worth eliminating are ones and zeros.** Going through a posting only to see
it is senior work — you are required to have five years of experience — or that it is an
on-site job outside your perimeter, where there is no way you are going to get hired.
Those are not rankings. They are easy factors that you can eliminate as a one or a zero,
and I want them gone before I read the list.

**The second problem was that I had no database.** You would have to manually type out
that you applied here, this and that. I wanted that better, and I wanted everything in
one spot.

**It should be matchmaking based.** At the beginning of the process the user uploads his
CV, and then through some kind of questionnaire it works out what jobs are good for him.
I might not have Angular in my CV, but it is no problem for me to learn Angular, because
Angular shares some stuff with React.

**Coding jobs only.** I want to just look for jobs that include coding. There is no point
in me getting job offers that are only for students — that doesn't make sense. That should
be a minimum match.

**"React developer" should score high.** Not match immediately, but it should be a high
match. The match should depend on seniority too.

**Where this goes.** You wouldn't have to be looking for jobs. Maybe in the future a
Telegram bot that just sends you the really good offers. And if there is nothing like this
in Slovakia, push it further and make it for jobs abroad as well.

## Decisions (2026-10-04, asked and answered)

- **A Slovak job outside Košice that claims remote is ranked lower, not cut.** Profesia's
  work-mode column is scraped from ad copy, so "možnosť práce z domu" on a Bratislava
  office job is a perk and not a work permit — but the prose cannot tell that ad from a
  genuinely remote one, so it keeps half a location (`scoring.REACH_CLAIMED`) and sits
  below work that is certainly reachable. Only a town with no remote claim at all is a cut.
- **An entry-level title must also name coding.** This *narrows* 2026-10-03's "internship,
  working student … are the engagements being hunted": those engagements are still what is
  wanted, but a title saying only "študent" or "brigádnik" and naming no trade is a miss
  like any other. On the live pool every such title was a shop floor, an assembly line, a
  law firm or an assistant's desk. The cost is accepted: a bare "Trainee programme" that
  names no trade is lost with them.
- **Adjacent stacks count, and now actually do.** `config.SKILL_ADJACENCY` is the Angular
  sentence above, made into a rule: a title naming a neighbouring technology scores just
  under one naming his own, and a requirement he could pick up is worth half of one he has.
