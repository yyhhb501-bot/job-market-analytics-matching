// Starts a disposable API server for Playwright E2E runs: fresh SQLite DB,
// seeded with the demo data set, no rate limiting, metrics off.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(webDir, "..", "..", "..");

function findPython() {
  const venvWindows = path.join(repoRoot, ".venv", "Scripts", "python.exe");
  const venvPosix = path.join(repoRoot, ".venv", "bin", "python");
  if (process.env.E2E_PYTHON) return process.env.E2E_PYTHON;
  if (existsSync(venvWindows)) return venvWindows;
  if (existsSync(venvPosix)) return venvPosix;
  return "python";
}

const python = findPython();
const dbFile = path.join(repoRoot, ".e2e.db");
if (existsSync(dbFile)) rmSync(dbFile);

const env = {
  ...process.env,
  DATABASE_URL: `sqlite+pysqlite:///${dbFile.replace(/\\/g, "/")}`,
  AUTO_CREATE_TABLES: "true",
  RATE_LIMIT_ENABLED: "false",
  RATE_LIMIT_BACKEND: "memory",
  ENABLE_METRICS: "false",
  // Write endpoints fail closed without a configured key; the web proxy
  // attaches this same value server-side (see playwright.config.ts).
  API_KEY: process.env.API_KEY || "e2e-api-key",
};

const seeded = spawnSync(
  python,
  ["-m", "apps.worker.main", "seed-demo"],
  { cwd: repoRoot, env, stdio: "inherit" },
);
if (seeded.status !== 0) {
  console.error("seed-demo failed");
  process.exit(seeded.status ?? 1);
}

const server = spawn(
  python,
  ["-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "8011"],
  { cwd: repoRoot, env, stdio: "inherit" },
);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.kill(signal));
}
server.on("exit", (code) => process.exit(code ?? 0));
