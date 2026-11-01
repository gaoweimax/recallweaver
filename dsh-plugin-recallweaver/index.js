import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export const name = "recallweaver-memory";
export const inject = ["systemPrompt"];

const PROMPT_SECTION = "recallweaver:memory";
const DEFAULT_TIMEOUT_MS = 10_000;
const CLI_BRIDGE_PATH = fileURLToPath(
  new URL("./cli-bridge.py", import.meta.url),
);

function messageText(event) {
  const data = event?.data;
  if (typeof data?.text === "string") return data.text;
  if (typeof data?.content === "string") return data.content;
  if (!Array.isArray(data?.content)) return "";

  return data.content
    .filter((block) => block && typeof block.text === "string")
    .map((block) => block.text)
    .join("\n");
}

function latestUserMessage(agent) {
  const events = agent?.session?.events;
  if (!Array.isArray(events)) return undefined;

  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event?.type !== "user/message") continue;
    const text = messageText(event).trim();
    if (text) return text;
  }
  return undefined;
}

export function recallWithCli(message, config = {}) {
  if (typeof message !== "string" || !message.trim()) {
    throw new TypeError("RecallWeaver requires a non-empty user message.");
  }

  const python = config.python || process.env.RECALLWEAVER_PYTHON || "python";
  const env = { ...process.env, PYTHONIOENCODING: "utf-8" };
  if (config.dbPath) env.DB_PATH = config.dbPath;

  const result = spawnSync(
    python,
    [CLI_BRIDGE_PATH, "recall", message],
    {
      encoding: "utf8",
      env,
      timeout: config.timeoutMs ?? DEFAULT_TIMEOUT_MS,
      windowsHide: true,
    },
  );

  if (result.error) {
    throw new Error(
      `RecallWeaver could not run Python (${python}): ${result.error.message}`,
      { cause: result.error },
    );
  }
  if (result.status !== 0) {
    const details = result.stderr?.trim() || "Python CLI exited unsuccessfully.";
    throw new Error(`RecallWeaver CLI failed: ${details}`);
  }

  const output = result.stdout.trim();
  if (!output) throw new Error("RecallWeaver CLI returned empty output.");
  return output;
}

export function apply(ctx, config = {}) {
  const resolvedConfig = { ...config };

  ctx.effect(
    () =>
      ctx.systemPrompt.section({
        name: PROMPT_SECTION,
        order: ctx.systemPrompt.getSectionOrder("DEPLOYMENT_PERSONA_SUFFIX") + 1,
        text: (context) => {
          const message = latestUserMessage(context.agent);
          if (!message) return "";
          return recallWithCli(message, resolvedConfig);
        },
      }),
    "recallweaver-memory.systemPrompt",
  );
}
