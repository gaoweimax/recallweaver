import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const name = "recallweaver-dsh";
export const inject = ["systemPrompt"];

const PLUGIN_DIR = path.dirname(fileURLToPath(import.meta.url));
const BRIDGE_PATH = path.join(PLUGIN_DIR, "bridge.py");
const PROMPT_SECTION = "recallweaver:memory";
const DEFAULT_TIMEOUT_MS = 10_000;

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
    if (text) {
      return {
        id: event.data?.id ?? `${event.seq ?? index}:${text}`,
        text,
      };
    }
  }
  return undefined;
}

function makeSystemPrompt(config, context, message) {
  const agent = context.agent;
  const session = agent?.session;
  const userId = config.userId || agent?.id || session?.id;
  if (typeof userId !== "string" || !userId) {
    throw new Error(
      "RecallWeaver DSH plugin could not determine a user ID; set config.userId.",
    );
  }

  const python = config.python || process.env.RECALLWEAVER_PYTHON || "python";
  const timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const env = { ...process.env };
  if (config.dbPath) env.RECALLWEAVER_DB_PATH = config.dbPath;

  const result = spawnSync(python, [BRIDGE_PATH], {
    encoding: "utf8",
    input: JSON.stringify({ user_id: userId, message }),
    timeout: timeoutMs,
    env,
    windowsHide: true,
  });

  if (result.error) {
    throw new Error(
      `RecallWeaver bridge could not run Python (${python}): ${result.error.message}`,
      { cause: result.error },
    );
  }
  if (result.status !== 0) {
    const details = result.stderr?.trim() || "Python bridge exited unsuccessfully.";
    throw new Error(`RecallWeaver DSH bridge failed: ${details}`);
  }

  const prompt = result.stdout.trim();
  if (!prompt) {
    throw new Error("RecallWeaver DSH bridge returned an empty System Prompt.");
  }
  return prompt;
}

export function apply(ctx, config = {}) {
  const resolvedConfig = { ...config };
  const cache = new WeakMap();

  ctx.effect(
    () =>
      ctx.systemPrompt.section({
        name: PROMPT_SECTION,
        order: ctx.systemPrompt.getSectionOrder("DEPLOYMENT_PERSONA_SUFFIX") + 1,
        text: (context) => {
          const agent = context.agent;
          const session = agent?.session;
          if (!session || (typeof session !== "object" && typeof session !== "function")) {
            return "";
          }

          const latest = latestUserMessage(agent);
          if (!latest) return "";

          const cached = cache.get(session);
          if (cached?.messageId === latest.id) return cached.prompt;

          const prompt = makeSystemPrompt(resolvedConfig, context, latest.text);
          cache.set(session, { messageId: latest.id, prompt });
          return prompt;
        },
      }),
    "recallweaver-dsh.systemPrompt",
  );
}
