# Remember portal sign-in

- [x] Update `web/src/auth.ts` to use Microsoft's supported cross-tab cache
  and remember the active account through MSAL, not a custom credential cookie.
- [x] Isolate the existing CloudSession component for focused tests. Reuse
  native Entra SSO with one guarded top-level redirect when the platform has
  already authenticated the browser. Preserve explicit sign-in fallback,
  silent API-token acquisition and MSAL/native logout without redirect loops.
- [x] Test remembered accounts, automatic SSO, failed restoration/manual retry
  and logout. Run frontend lint/types/tests/build/format and document session,
  KMSI, browser and Conditional Access limits. No development commands change.
  111 frontend tests, lint/types/build and Prettier pass; no dependencies added.
- [x] Validate/package/deploy web only to the existing publicdemo environment.
  Verify deployment and native sign-in protection; do not simulate MFA or claim
  an interactive browser round trip without a real session.
  Final web deployment succeeded; azd confirmed the portal endpoint and native
  protection returns302 for browser sign-in and401 for unauthenticated config.
  No infrastructure apply. Interactive Entra/MFA/browser-restart validation
  remains explicitly unverified; tenant KMSI/session policy is not overridden.
