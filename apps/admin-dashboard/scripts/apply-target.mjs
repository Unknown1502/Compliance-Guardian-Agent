// Binds the Firebase Hosting deploy target to a site ID supplied at deploy
// time. The site ID is deliberately NOT committed: it must be neutral and
// unrelated to the customer project, and choosing it is an operator decision,
// not something baked into the repository.
//
// The Firebase project is passed explicitly rather than relying on a
// .firebaserc, because that file records the chosen site ID and is therefore
// gitignored — without --project, firebase-tools has no active project and
// target:apply fails.

import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";

function fail(lines) {
  console.error("\n" + lines.join("\n") + "\n");
  process.exit(1);
}

const siteId = process.env.ADMIN_SITE_ID;

if (!siteId) {
  fail([
    "ADMIN_SITE_ID is not set.",
    "",
    "Pick a NEUTRAL Firebase Hosting site ID — one that does not reveal the",
    "customer project, product name, or tenant identifiers. Create it once:",
    "",
    "  npx firebase-tools hosting:sites:create <ADMIN_SITE_ID> --project <FIREBASE_PROJECT_ID>",
    "",
    "Then deploy with it set:",
    "",
    "  ADMIN_SITE_ID=<ADMIN_SITE_ID> npm run deploy          (bash)",
    "  set ADMIN_SITE_ID=<ADMIN_SITE_ID> && npm run deploy   (cmd.exe)",
  ]);
}

if (!/^[a-z0-9-]{3,30}$/.test(siteId)) {
  fail([`ADMIN_SITE_ID "${siteId}" must be 3-30 chars: lowercase letters, digits, hyphens.`]);
}

/** Project id from the environment, else from .env.local. */
function resolveProjectId() {
  if (process.env.FIREBASE_PROJECT_ID) return process.env.FIREBASE_PROJECT_ID;
  try {
    const env = readFileSync(new URL("../.env.local", import.meta.url), "utf8");
    const match = env.match(/^VITE_FIREBASE_PROJECT_ID=(.+)$/m);
    if (match) return match[1].trim();
  } catch {
    /* no .env.local — fall through to the error below */
  }
  return "";
}

const projectId = resolveProjectId();
if (!projectId) {
  fail([
    "Could not determine the Firebase project.",
    "",
    "Set FIREBASE_PROJECT_ID, or put VITE_FIREBASE_PROJECT_ID in .env.local",
    "(copy .env.example to .env.local and fill it in).",
  ]);
}

execSync(
  `npx firebase-tools target:apply hosting admin-control ${siteId} --project ${projectId}`,
  { stdio: "inherit" },
);

// target:apply records the target but leaves "projects" empty, so a following
// `firebase deploy` would have no default project. Set it here so the deploy
// step needs no extra flags.
const rcPath = new URL("../.firebaserc", import.meta.url);
const rc = JSON.parse(readFileSync(rcPath, "utf8"));
rc.projects = { ...(rc.projects ?? {}), default: projectId };
writeFileSync(rcPath, JSON.stringify(rc, null, 2) + "\n");

console.log(`\nHosting target 'admin-control' -> site '${siteId}' (project ${projectId})`);
