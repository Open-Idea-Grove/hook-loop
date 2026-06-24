const HOOK_BIN = "/home/blizhan/.paseo/worktrees/0qsy20m0/mad-zebra/.venv/bin/hook-loop";
const CONFIG = "/home/blizhan/.paseo/worktrees/0qsy20m0/mad-zebra/hook-loop.json";
const EVENT_LOG = "/home/blizhan/.paseo/worktrees/0qsy20m0/mad-zebra/.hook-loop/events.jsonl";

async function callHookLoop(event, payload) {
  const input = JSON.stringify(payload);
  try {
    const proc = Bun.spawn({
      cmd: [HOOK_BIN, "opencode-hook", "--event", event, "--config", CONFIG, "--event-log", EVENT_LOG],
      stdin: new TextEncoder().encode(input),
      stdout: "pipe",
      stderr: "pipe",
    });
    const exitCode = await proc.exited;
    const stdout = await new Response(proc.stdout).text();
    const stderr = await new Response(proc.stderr).text();
    return { exitCode, stdout, stderr };
  } catch (err) {
    return { exitCode: err.exitCode ?? 1, stdout: "", stderr: String(err) };
  }
}

function enforceHookDecision(result, fallbackMessage) {
  if (result.exitCode === 2) {
    throw new Error(result.stdout || fallbackMessage);
  }
}

export const HookLoopPlugin = async ({ project, client, directory, worktree }) => {
  const sessionId = project?.id ?? "opencode-session";
  const cwd = directory ?? "";

  // Fire session.created without blocking plugin initialization (#14 fix):
  // awaiting the hook subprocess here blocks opencode's main loop before the
  // model even starts.  opencode emits a `session.created` event later that
  // the event handler catches, so this explicit call is redundant.
  return {
    "tool.execute.before": async (input, output) => {
      const payload = {
        session_id: sessionId,
        cwd,
        tool: input?.tool ?? input?.name ?? "unknown",
        input: output?.args ?? {},
        workspace: worktree,
      };
      const result = await callHookLoop("tool.execute.before", payload);
      enforceHookDecision(result, "blocked by hook-loop policy");
    },
    "tool.execute.after": async (input, output) => {
      const payload = {
        session_id: sessionId,
        cwd,
        tool: input?.tool ?? input?.name ?? "unknown",
        input: output?.args ?? input?.args ?? {},
        output: {
          exit_code: output?.exitCode ?? output?.exit_code ?? 0,
          stdout: output?.stdout ?? output?.output ?? "",
        },
        workspace: worktree,
      };
      await callHookLoop("tool.execute.after", payload);
    },
    event: async ({ event }) => {
      const eventType = event?.type ?? "";
      if (eventType === "session.idle" || (eventType === "session.status" && event?.properties?.status === "idle")) {
        const payload = { session_id: sessionId, cwd, workspace: worktree };
        const result = await callHookLoop("session.idle", payload);
        enforceHookDecision(result, "blocked by hook-loop stop policy");
        return;
      }
      if (eventType === "session.created" || eventType === "session.init") {
        const payload = { session_id: sessionId, cwd, workspace: worktree };
        await callHookLoop("session.created", payload);
        return;
      }
      // message.updated: opencode puts role inside properties.info.role (#18 fix).
      // Text content is not in message.updated; we fire with empty text so that
      // prompt_not_match rules (like kickoff) still trigger, while prompt_match
      // rules (like plan_ready) need text from message.part.updated below.
      if (eventType === "message.updated") {
        const info = event?.properties?.info ?? {};
        const role = info.role ?? "";
        if (role === "user" || role === "assistant") {
          const payload = { session_id: sessionId, cwd, text: "", workspace: worktree };
          await callHookLoop("message.updated", payload);
        }
      }
      // message.part.updated: carries actual text content for the message.
      // Fire with the accumulated text so prompt_match rules can match keywords.
      if (eventType === "message.part.updated") {
        const part = event?.properties?.part ?? event?.properties?.info ?? {};
        const text = part.text ?? part.content ?? "";
        const role = part.role ?? event?.properties?.info?.role ?? "";
        if (text && (role === "user" || role === "assistant")) {
          const payload = { session_id: sessionId, cwd, text, workspace: worktree };
          await callHookLoop("message.updated", payload);
        }
      }
      // Stop gate: fire on session.idle or session.status with idle
      if (eventType === "session.idle" || (eventType === "session.status" && event?.properties?.status === "idle")) {
        const payload = { session_id: sessionId, cwd, workspace: worktree };
        const result = await callHookLoop("session.idle", payload);
        enforceHookDecision(result, "blocked by hook-loop stop policy");
        return;
      }
      if (eventType === "session.created" || eventType === "session.init") {
        const payload = { session_id: sessionId, cwd, workspace: worktree };
        await callHookLoop("session.created", payload);
        return;
      }
      // UserPromptSubmit: fire on message.updated but only for completed user messages
      if (eventType === "message.updated") {
        const props = event?.properties ?? {};
        const role = props.role ?? props.message?.role ?? "";
        const text = props.text ?? props.content ?? "";
        // Only fire for assistant messages with actual text content, or user messages
        if (text && (role === "user" || role === "assistant" || role === "")) {
          const payload = { session_id: sessionId, cwd, text, workspace: worktree };
          await callHookLoop("message.updated", payload);
        }
      }
    },
  };
};
