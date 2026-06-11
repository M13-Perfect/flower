import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const candidates = [
  join(repoRoot, ".venv-win", "Scripts", "python.exe"),
  join(repoRoot, ".venv", "Scripts", "python.exe"),
  join(repoRoot, ".venv", "bin", "python.exe"),
  "python",
];

const python = candidates.find((candidate) => candidate === "python" || existsSync(candidate));
const result = spawnSync(python, process.argv.slice(2), {
  cwd: process.cwd(),
  env: process.env,
  shell: false,
  stdio: "inherit",
});

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
