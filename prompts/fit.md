# Fit check

Given the job posting and the candidate's verified profile, decide whether this job is
worth applying to.

1. Hard requirements the candidate fails: GPA cutoff, graduation window, degree level,
   work authorization or sponsorship, location, citizenship or clearance, start date.
   Any failed hard requirement means `apply: false`.
2. Score 1-10 how well the candidate's actual experience matches the core of the role.

Reply with only:

```json
{"apply": true, "fit_score": 7, "blockers": [], "gaps": ["..."], "why": "one sentence"}
```
