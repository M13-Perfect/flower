import { spawn, spawnSync } from "node:child_process";

const isWindows = process.platform === "win32";
const processes = [
  ["api", ["run", "dev", "--workspace", "@flower/api"]],
  ["desktop", ["run", "dev", "--workspace", "@flower/desktop"]],
];

let stopping = false;
const children = processes.map(([name, args]) => {
  const child = spawn("npm", args, {
    cwd: process.cwd(),
    env: process.env,
    shell: isWindows,
    stdio: ["ignore", "pipe", "pipe"],
  });

  child.stdout.on("data", (chunk) => process.stdout.write(`[${name}] ${chunk}`));
  child.stderr.on("data", (chunk) => process.stderr.write(`[${name}] ${chunk}`));
  child.on("exit", (code) => {
    if (code !== 0) {
      process.exitCode = code ?? 1;
      stopChildren();
    }
  });

  return child;
});

function stopChildren() {
  if (stopping) {
    return;
  }
  stopping = true;

  for (const child of children) {
    if (child.killed || child.exitCode !== null || child.pid === undefined) {
      continue;
    }

    if (isWindows) {
      spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
      });
    } else {
      child.kill("SIGTERM");
    }
  }
}

process.on("SIGINT", () => {
  stopChildren();
  process.exit(130);
});

process.on("SIGTERM", () => {
  stopChildren();
  process.exit(143);
});
