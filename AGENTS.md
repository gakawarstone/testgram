Testgram is, and must remain, a **pure black-box end-to-end testing framework**. This is a non-negotiable architectural invariant and must not be violated.

## Pull requests

- Write a concise English title in the imperative, such as `Fix isolation between directory scenarios`.
- Describe the concrete user scenario or problem and how the change affects behavior. Include relevant constraints or tradeoffs.
- For changes to user-facing YAML syntax or behavior, include at least one fenced YAML example directly in the PR description. Use supported syntax and explain the observable result. If the change affects an HTTP response or an error diagnostic, show the relevant output alongside the example.
- Include a `## Checks` or `## Tests` section with the actual commands run and their results. State honestly which checks were not run and why.
- Choose the rest of the description's structure to suit the change; there is no single required template.
