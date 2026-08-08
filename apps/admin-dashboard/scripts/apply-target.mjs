// Binds the Firebase Hosting deploy target to a site ID supplied at deploy
// time. The site ID is deliberately NOT committed: it must be neutral and
// unrelated to the customer project, and choosing it is an operator decision,
// not something baked into the repository.
import { execSync } from "node:child_process";

const siteId = process.env.ADMIN_SITE_ID;

if (!siteId) {
  console.error(
    [
      "",
      "ADMIN_SITE_ID is not set.",
      "",
      "Pick a NEUTRAL Firebase Hosting site ID — one that does not reveal the",
      "customer project, product name, or tenant identifiers. Create it once:",
      "",
      "  npx firebase-tools hosting:sites:create <ADMIN_SITE_ID> --project <FIREBASE_PROJECT_ID>",
      "",
      "Then deploy with it set, e.g.:",
      "",
      "  ADMIN_SITE_ID=<ADMIN_SITE_ID> npm run deploy          (bash)",
      "  set ADMIN_SITE_ID=<ADMIN_SITE_ID> && npm run deploy   (cmd.exe)",
      "",
    ].join("\n"),
  );
  process.exit(1);
}

if (!/^[a-z0-9-]{3,30}$/.test(siteId)) {
  console.error(`ADMIN_SITE_ID "${siteId}" must be 3-30 chars, lowercase letters, digits, hyphens.`);
  process.exit(1);
}

execSync(`npx firebase-tools target:apply hosting admin-control ${siteId}`, {
  stdio: "inherit",
});
console.log(`\nHosting target 'admin-control' -> site '${siteId}'`);
