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
