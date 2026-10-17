# npm advisory review (2026-10-17)

`npm audit` in `apps/web` reported five high findings. They are one chain:

`eslint-config-next` → `@next/eslint-plugin-next` → `fast-glob` → `micromatch` → `braces`

`braces` can exhaust the stack on a deeply nested glob. That code runs when ESLint loads the Next.js plugin during `npm run lint`. It is not imported by the production Next.js server, the browser bundle, or the Python API.

`npm ls braces micromatch fast-glob --omit=dev` does not place this chain in the production dependency tree. The running dashboard is `next start` of the compiled app. A malicious glob is not accepted from NomadQuant users.

No production package was upgraded in this pass. Forcing an ESLint-tree override would not change the served application and could break the pinned Next 16 lint plugin. The mitigation is to keep lint tooling on the developer machine and not to expose the ESLint process to untrusted glob patterns.
