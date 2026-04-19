import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND_API_URL =
  process.env.ADAPTER_BACKEND_URL ??
  process.env.LANGGRAPH_API_URL ??
  "http://api:8000";
const DEFAULT_ASSISTANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_ID ?? "agent";
const DEVICE_COOKIE_KEY = "dyslexia_device_id";
const DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1 year

type BackendHistoryMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  client_msg_id?: string;
};

type BackendHistoryResponse = {
  thread_id: string;
  messages: BackendHistoryMessage[];
};

type BackendProcess = {
  process_id: string;
  status: string;
  session_type?: string;
  report_id?: string | null;
  created_at: string;
  updated_at: string;
  preview?: string | null;
};

type BackendThreadReport = {
  thread_id: string;
  session_type: string;
  report_id?: string | null;
  report_text: string;
  title?: string;
};

type AdapterState = {
  messages: Array<Record<string, unknown>>;
};

type RouteContext = {
  params: Promise<{ _path?: string[] }>;
};

function buildBackendUrl(path: string): string {
  return new URL(path, BACKEND_API_URL).toString();
}

function ensureIso(ts?: string): string {
  if (!ts) return new Date().toISOString();
  return ts;
}

function extractTextFromMessageContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (
        part &&
        typeof part === "object" &&
        "type" in part &&
        (part as { type?: string }).type === "text" &&
        "text" in part
      ) {
        const text = (part as { text?: unknown }).text;
        return typeof text === "string" ? text : "";
      }
      return "";
    })
    .filter(Boolean)
    .join(" ");
}

function toUiMessage(
  role: BackendHistoryMessage["role"],
  content: string,
  id: string,
): Record<string, unknown> {
  const type =
    role === "user" ? "human" : role === "assistant" ? "ai" : "system";
  return {
    id,
    type,
    content,
  };
}

function resolveHistoryMessageId(
  threadId: string,
  message: BackendHistoryMessage,
  index: number,
): string {
  const rawClientMsgId =
    typeof message.client_msg_id === "string"
      ? message.client_msg_id.trim()
      : "";

  if (!rawClientMsgId) {
    return `${threadId}-m-${index}`;
  }
  if (message.role === "user") {
    return rawClientMsgId;
  }
  if (message.role === "assistant") {
    return `ai-${rawClientMsgId}`;
  }
  return `${threadId}-m-${index}`;
}

function normalizeHistoryToMessages(
  threadId: string,
  historyMessages: BackendHistoryMessage[],
): Array<Record<string, unknown>> {
  return historyMessages.map((item, index) => {
    const id = resolveHistoryMessageId(threadId, item, index);
    return toUiMessage(item.role, item.content, id);
  });
}

function appendPendingHumanMessage(
  baseMessages: Array<Record<string, unknown>>,
  messageId: string,
  content: string,
): Array<Record<string, unknown>> {
  const normalizedId = messageId.trim();
  if (!normalizedId || !content.trim()) return baseMessages;
  const exists = baseMessages.some(
    (msg) => typeof msg.id === "string" && msg.id === normalizedId,
  );
  if (exists) return baseMessages;
  return [
    ...baseMessages,
    {
      id: normalizedId,
      type: "human",
      content,
    },
  ];
}

function buildThreadState(
  threadId: string,
  historyMessages: BackendHistoryMessage[],
): Record<string, unknown> {
  const messages = normalizeHistoryToMessages(threadId, historyMessages);
  const lastTs = historyMessages.at(-1)?.created_at;
  const checkpointId = `${threadId}-cp-${historyMessages.length}`;
  return {
    values: { messages },
    next: [],
    checkpoint: {
      thread_id: threadId,
      checkpoint_ns: "root",
      checkpoint_id: checkpointId,
      checkpoint_map: null,
    },
    metadata: {},
    created_at: ensureIso(lastTs),
    parent_checkpoint: null,
    tasks: [],
  };
}

function buildThreadSummary(
  threadId: string,
  assistantId: string,
  createdAt?: string,
  updatedAt?: string,
  values?: AdapterState,
  metadataExtra?: Record<string, unknown>,
): Record<string, unknown> {
  const created = ensureIso(createdAt);
  const updated = ensureIso(updatedAt ?? created);
  const metadata: Record<string, unknown> = {
    assistant_id: assistantId,
    graph_id: assistantId,
  };
  if (metadataExtra) {
    Object.assign(metadata, metadataExtra);
  }
  return {
    thread_id: threadId,
    created_at: created,
    updated_at: updated,
    state_updated_at: updated,
    metadata,
    status: "idle",
    values: values ?? { messages: [] },
    interrupts: {},
  };
}

function normalizeThreadPreview(
  value: unknown,
  maxLength = 80,
): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 3)}...`;
}

function sseEvent(event: string, data: unknown, id?: string): string {
  const lines = [];
  if (id) lines.push(`id: ${id}`);
  lines.push(`event: ${event}`);
  lines.push(`data: ${JSON.stringify(data)}`);
  return `${lines.join("\n")}\n\n`;
}

function extractSseBlocks(raw: string): { blocks: string[]; rest: string } {
  // Normalize CRLF streams so we can safely split on "\n\n".
  const normalized = raw.replace(/\r\n/g, "\n");
  const blocks: string[] = [];
  let rest = normalized;
  while (true) {
    const splitAt = rest.indexOf("\n\n");
    if (splitAt === -1) break;
    blocks.push(rest.slice(0, splitAt));
    rest = rest.slice(splitAt + 2);
  }
  return { blocks, rest };
}

function parseSseDataBlock(block: string): string | null {
  const dataLines = block
    .split("\n")
    .map((line) => line.trimEnd())
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trim());
  if (dataLines.length === 0) return null;
  return dataLines.join("\n");
}

function getOrCreateDeviceId(req: NextRequest): {
  deviceId: string;
  shouldSetCookie: boolean;
} {
  const fromCookie = req.cookies.get(DEVICE_COOKIE_KEY)?.value;
  if (fromCookie && fromCookie.trim().length > 0) {
    return { deviceId: fromCookie, shouldSetCookie: false };
  }
  return { deviceId: `web-${randomUUID()}`, shouldSetCookie: true };
}

function applyDeviceCookie(
  res: NextResponse,
  deviceId: string,
  shouldSetCookie: boolean,
): NextResponse {
  if (!shouldSetCookie) return res;
  res.cookies.set({
    name: DEVICE_COOKIE_KEY,
    value: deviceId,
    httpOnly: false,
    path: "/",
    maxAge: DEVICE_COOKIE_MAX_AGE,
    sameSite: "lax",
  });
  return res;
}

function buildBackendCookieHeader(deviceId: string): HeadersInit {
  return { Cookie: `${DEVICE_COOKIE_KEY}=${encodeURIComponent(deviceId)}` };
}

async function safeParseJson(req: NextRequest): Promise<Record<string, any>> {
  try {
    const data = await req.json();
    if (data && typeof data === "object") return data;
    return {};
  } catch {
    return {};
  }
}

async function fetchBackendHistory(
  deviceId: string,
  processId: string,
): Promise<BackendHistoryResponse> {
  const params = new URLSearchParams({
    device_id: deviceId,
    process_id: processId,
  });
  const res = await fetch(buildBackendUrl(`/history?${params.toString()}`), {
    method: "GET",
    cache: "no-store",
  });
  if (!res.ok) {
    if (res.status === 404) {
      return { thread_id: processId, messages: [] };
    }
    const detail = await res.text();
    throw new Error(`history fetch failed: ${res.status} ${detail}`);
  }
  return (await res.json()) as BackendHistoryResponse;
}

async function fetchBackendThreadSummary(
  deviceId: string,
  threadId: string,
): Promise<Record<string, unknown> | null> {
  const res = await fetch(
    buildBackendUrl(`/threads/${encodeURIComponent(threadId)}`),
    {
      method: "GET",
      cache: "no-store",
      headers: buildBackendCookieHeader(deviceId),
    },
  );
  if (!res.ok) {
    if (res.status === 404) return null;
    const detail = await res.text();
    throw new Error(`thread fetch failed: ${res.status} ${detail}`);
  }
  const payload = await res.json();
  return payload && typeof payload === "object"
    ? (payload as Record<string, unknown>)
    : null;
}

function extractLatestHumanFromInput(input: unknown): {
  message: string;
  clientMsgId: string;
  allMessages: Array<Record<string, unknown>>;
} | null {
  if (!input || typeof input !== "object") return null;
  const source = (input as { messages?: unknown }).messages;
  if (!Array.isArray(source)) return null;
  const allMessages = source.filter(
    (item): item is Record<string, unknown> =>
      item !== null && typeof item === "object",
  );
  for (let i = allMessages.length - 1; i >= 0; i -= 1) {
    const msg = allMessages[i];
    if (msg.type !== "human") continue;
    const text = extractTextFromMessageContent(msg.content);
    if (!text.trim()) continue;
    const id =
      typeof msg.id === "string" && msg.id.trim().length > 0
        ? msg.id
        : randomUUID();
    return { message: text, clientMsgId: id, allMessages };
  }
  return null;
}

async function handleInfo(req: NextRequest): Promise<NextResponse> {
  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  const res = NextResponse.json({
    name: "dyslexia-ai-mvp-adapter",
    version: "0.1.0",
    transport: "langgraph-compatible-subset",
  });
  return applyDeviceCookie(res, deviceId, shouldSetCookie);
}

async function handleCreateThread(req: NextRequest): Promise<NextResponse> {
  const body = await safeParseJson(req);
  const threadId =
    typeof body.thread_id === "string" && body.thread_id.trim().length > 0
      ? body.thread_id
      : randomUUID();
  const assistantId =
    (body?.metadata?.assistant_id as string | undefined) ||
    (body?.metadata?.graph_id as string | undefined) ||
    DEFAULT_ASSISTANT_ID;
  const sessionType = String(body?.metadata?.session_type ?? "").trim();
  const reportId = String(body?.metadata?.report_id ?? "").trim();
  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  // Best-effort process pre-registration so the new thread appears in history immediately.
  const initParams = new URLSearchParams({
    device_id: deviceId,
    process_id: threadId,
  });
  if (sessionType) {
    initParams.set("session_type", sessionType);
  }
  if (reportId) {
    initParams.set("report_id", reportId);
  }
  fetch(
    buildBackendUrl(`/processes/init?${initParams.toString()}`),
    { method: "POST" },
  ).catch((err) => {
    console.warn("process init failed", err);
  });
  const metadataExtra =
    sessionType.toLowerCase() === "report"
      ? {
          session_type: "report",
          ...(reportId ? { report_id: reportId } : {}),
        }
      : undefined;
  const payload = buildThreadSummary(
    threadId,
    assistantId,
    undefined,
    undefined,
    undefined,
    metadataExtra,
  );
  const res = NextResponse.json(payload);
  return applyDeviceCookie(res, deviceId, shouldSetCookie);
}

async function handleSearchThreads(req: NextRequest): Promise<NextResponse> {
  const body = await safeParseJson(req);
  const limit =
    typeof body.limit === "number" && Number.isFinite(body.limit)
      ? Math.max(1, Math.min(200, body.limit))
      : 100;
  const assistantId =
    (body?.metadata?.assistant_id as string | undefined) ||
    (body?.metadata?.graph_id as string | undefined) ||
    DEFAULT_ASSISTANT_ID;

  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  let processes: BackendProcess[] = [];
  try {
    const params = new URLSearchParams({
      device_id: deviceId,
      limit: String(limit),
      offset: "0",
    });
    const res = await fetch(buildBackendUrl(`/processes?${params.toString()}`), {
      method: "GET",
      cache: "no-store",
    });
    if (res.ok) {
      const data = (await res.json()) as { items?: BackendProcess[] };
      processes = Array.isArray(data.items) ? data.items : [];
    }
  } catch (err) {
    console.warn("threads/search fallback to empty list", err);
  }

  const threads = processes.map((item) => {
    const preview = normalizeThreadPreview(item.preview);
    const summary = buildThreadSummary(
      item.process_id,
      assistantId,
      item.created_at,
      item.updated_at,
      preview
        ? {
            messages: [
              {
                id: `${item.process_id}-preview`,
                type: "human",
                content: preview,
              },
            ],
          }
        : { messages: [] },
      preview
        ? {
            title: preview,
            preview,
          }
        : undefined,
    );
    const normalizedSessionType = String(item.session_type ?? "").trim().toLowerCase();
    if (normalizedSessionType === "report") {
      const metadata = (summary.metadata ?? {}) as Record<string, unknown>;
      summary.metadata = {
        ...metadata,
        session_type: "report",
        ...(item.report_id ? { report_id: item.report_id } : {}),
      };
    }
    return summary;
  });

  const response = NextResponse.json(threads);
  return applyDeviceCookie(response, deviceId, shouldSetCookie);
}

async function handleDeleteThread(
  req: NextRequest,
  threadId: string,
): Promise<NextResponse> {
  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  const params = new URLSearchParams({ device_id: deviceId });
  const backendRes = await fetch(
    buildBackendUrl(
      `/processes/${encodeURIComponent(threadId)}?${params.toString()}`,
    ),
    {
      method: "DELETE",
    },
  );

  if (!backendRes.ok) {
    const detail = await backendRes.text();
    const errorRes = NextResponse.json(
      { error: `delete thread failed: ${backendRes.status} ${detail}` },
      { status: backendRes.status || 500 },
    );
    return applyDeviceCookie(errorRes, deviceId, shouldSetCookie);
  }

  const response = NextResponse.json({ thread_id: threadId, status: "deleted" });
  return applyDeviceCookie(response, deviceId, shouldSetCookie);
}

async function handleThreadGet(
  req: NextRequest,
  threadId: string,
): Promise<NextResponse> {
  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  try {
    const backendThread = await fetchBackendThreadSummary(deviceId, threadId);
    if (backendThread) {
      const proxyRes = NextResponse.json(backendThread);
      return applyDeviceCookie(proxyRes, deviceId, shouldSetCookie);
    }
  } catch (err) {
    console.warn("threads/get fallback to history path", err);
  }

  const history = await fetchBackendHistory(deviceId, threadId);
  const messages = normalizeHistoryToMessages(threadId, history.messages);
  const summary = buildThreadSummary(
    threadId,
    DEFAULT_ASSISTANT_ID,
    history.messages[0]?.created_at,
    history.messages.at(-1)?.created_at,
    { messages },
  );
  const res = NextResponse.json(summary);
  return applyDeviceCookie(res, deviceId, shouldSetCookie);
}

async function handleThreadReport(
  req: NextRequest,
  threadId: string,
): Promise<NextResponse> {
  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  const backendRes = await fetch(
    buildBackendUrl(`/threads/${encodeURIComponent(threadId)}/report`),
    {
      method: "GET",
      cache: "no-store",
      headers: buildBackendCookieHeader(deviceId),
    },
  );

  if (!backendRes.ok) {
    let payload: Record<string, unknown>;
    try {
      payload = (await backendRes.json()) as Record<string, unknown>;
    } catch {
      const detail = await backendRes.text();
      payload = {
        error: "report_fetch_failed",
        message: `report fetch failed: ${backendRes.status} ${detail}`,
      };
    }
    const errorRes = NextResponse.json(payload, {
      status: backendRes.status || 500,
    });
    return applyDeviceCookie(errorRes, deviceId, shouldSetCookie);
  }

  const payload = (await backendRes.json()) as BackendThreadReport;
  const response = NextResponse.json(payload);
  return applyDeviceCookie(response, deviceId, shouldSetCookie);
}

async function handleThreadHistory(
  req: NextRequest,
  threadId: string,
): Promise<NextResponse> {
  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  const history = await fetchBackendHistory(deviceId, threadId);
  const states =
    history.messages.length > 0
      ? [buildThreadState(threadId, history.messages)]
      : [];
  const res = NextResponse.json(states);
  return applyDeviceCookie(res, deviceId, shouldSetCookie);
}

async function handleThreadState(
  req: NextRequest,
  threadId: string,
): Promise<NextResponse> {
  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  const history = await fetchBackendHistory(deviceId, threadId);
  const state = buildThreadState(threadId, history.messages);
  const res = NextResponse.json(state);
  return applyDeviceCookie(res, deviceId, shouldSetCookie);
}

async function handleRunStream(
  req: NextRequest,
  threadId: string,
): Promise<NextResponse> {
  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  const body = await safeParseJson(req);
  const latestHuman = extractLatestHumanFromInput(body.input);

  let outgoingMessage = latestHuman?.message ?? "";
  const clientMsgId = latestHuman?.clientMsgId ?? `regen-${Date.now()}`;
  const history = await fetchBackendHistory(deviceId, threadId);
  let baseMessages = normalizeHistoryToMessages(threadId, history.messages);

  if (!outgoingMessage.trim()) {
    const lastUser = [...history.messages]
      .reverse()
      .find((item) => item.role === "user");
    if (!lastUser) {
      const badReq = NextResponse.json(
        {
          error:
            "Adapter cannot infer user input. Please submit a human message first.",
        },
        { status: 400 },
      );
      return applyDeviceCookie(badReq, deviceId, shouldSetCookie);
    }
    outgoingMessage = lastUser.content;
  } else {
    baseMessages = appendPendingHumanMessage(
      baseMessages,
      clientMsgId,
      outgoingMessage,
    );
  }

  const backendRes = await fetch(buildBackendUrl("/chat"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      device_id: deviceId,
      process_id: threadId,
      client_msg_id: clientMsgId,
      message: outgoingMessage,
    }),
  });

  if (!backendRes.ok || !backendRes.body) {
    const detail = await backendRes.text();
    const errorRes = NextResponse.json(
      { error: `chat failed: ${backendRes.status} ${detail}` },
      { status: backendRes.status || 500 },
    );
    return applyDeviceCookie(errorRes, deviceId, shouldSetCookie);
  }

  const runId = randomUUID();
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  let eventSeq = 0;
  let assistantText = "";
  const aiMessageId = `${threadId}-ai-${runId}`;
  const aiBase = { id: aiMessageId, type: "ai" as const };

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const emitValues = (messages: Array<Record<string, unknown>>) => {
        controller.enqueue(
          encoder.encode(
            sseEvent(
              "values",
              {
                messages,
              },
              String(eventSeq++),
            ),
          ),
        );
      };

      const emitError = (error: string, message?: string) => {
        controller.enqueue(
          encoder.encode(
            sseEvent(
              "error",
              {
                error,
                message: message ?? error,
              },
              String(eventSeq++),
            ),
          ),
        );
      };

      const processBackendSseBlock = (block: string) => {
        const dataText = parseSseDataBlock(block);
        if (!dataText || dataText === "[DONE]") return;

        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(dataText) as Record<string, unknown>;
        } catch {
          return;
        }

        if (typeof payload.error === "string") {
          emitError(payload.error, payload.error);
          return;
        }

        if (payload.status === "processing") {
          emitError(
            "already_processing",
            "A response is already being generated for this message. Please retry shortly.",
          );
          return;
        }

        if (typeof payload.text === "string") {
          assistantText += payload.text;
          emitValues([
            ...baseMessages,
            {
              ...aiBase,
              content: assistantText,
            },
          ]);
        }
      };

      emitValues(baseMessages);

      const reader = backendRes.body!.getReader();
      let buffer = "";

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { blocks, rest } = extractSseBlocks(buffer);
          buffer = rest;
          for (const block of blocks) {
            processBackendSseBlock(block);
          }
        }

        const tail = decoder.decode();
        if (tail) buffer += tail;
        if (buffer.trim()) {
          processBackendSseBlock(buffer);
        }
      } catch (err) {
        emitError(
          "adapter_stream_error",
          err instanceof Error ? err.message : String(err),
        );
      } finally {
        controller.close();
      }
    },
  });

  const res = new NextResponse(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "Content-Location": `/threads/${threadId}/runs/${runId}`,
      Location: `/threads/${threadId}/runs/${runId}/stream`,
    },
  });

  return applyDeviceCookie(res, deviceId, shouldSetCookie);
}

async function handleJoinRunStream(
  req: NextRequest,
  threadId: string,
): Promise<NextResponse> {
  const { deviceId, shouldSetCookie } = getOrCreateDeviceId(req);
  const history = await fetchBackendHistory(deviceId, threadId);
  const state = buildThreadState(threadId, history.messages);
  const payload = sseEvent("values", state.values, "0");
  const res = new NextResponse(payload, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
  return applyDeviceCookie(res, deviceId, shouldSetCookie);
}

async function routeRequest(req: NextRequest, ctx: RouteContext) {
  const { _path = [] } = await Promise.resolve(ctx.params);
  const safePath = `/${_path.map((part) => decodeURIComponent(part)).join("/")}`;
  const method = req.method.toUpperCase();

  if (method === "OPTIONS") {
    return NextResponse.json({}, { status: 204 });
  }

  if (method === "GET" && safePath === "/info") {
    return handleInfo(req);
  }

  if (method === "POST" && safePath === "/threads") {
    return handleCreateThread(req);
  }

  if (method === "POST" && safePath === "/threads/search") {
    return handleSearchThreads(req);
  }

  const threadGetMatch = safePath.match(/^\/threads\/([^/]+)$/);
  if (method === "DELETE" && threadGetMatch) {
    return handleDeleteThread(req, threadGetMatch[1]);
  }
  if (method === "GET" && threadGetMatch) {
    return handleThreadGet(req, threadGetMatch[1]);
  }

  const reportMatch = safePath.match(/^\/threads\/([^/]+)\/report$/);
  if (method === "GET" && reportMatch) {
    return handleThreadReport(req, reportMatch[1]);
  }

  const historyMatch = safePath.match(/^\/threads\/([^/]+)\/history$/);
  if (method === "POST" && historyMatch) {
    return handleThreadHistory(req, historyMatch[1]);
  }

  const stateMatch = safePath.match(/^\/threads\/([^/]+)\/state$/);
  if (method === "GET" && stateMatch) {
    return handleThreadState(req, stateMatch[1]);
  }

  const streamMatch = safePath.match(/^\/threads\/([^/]+)\/runs\/stream$/);
  if (method === "POST" && streamMatch) {
    return handleRunStream(req, streamMatch[1]);
  }

  const joinStreamMatch = safePath.match(
    /^\/threads\/([^/]+)\/runs\/([^/]+)\/stream$/,
  );
  if (method === "GET" && joinStreamMatch) {
    return handleJoinRunStream(req, joinStreamMatch[1]);
  }

  return NextResponse.json(
    {
      error: "not_implemented",
      message: `Adapter does not implement ${method} ${safePath}`,
    },
    { status: 404 },
  );
}

export async function GET(req: NextRequest, ctx: RouteContext) {
  return routeRequest(req, ctx);
}

export async function POST(req: NextRequest, ctx: RouteContext) {
  return routeRequest(req, ctx);
}

export async function PUT(req: NextRequest, ctx: RouteContext) {
  return routeRequest(req, ctx);
}

export async function PATCH(req: NextRequest, ctx: RouteContext) {
  return routeRequest(req, ctx);
}

export async function DELETE(req: NextRequest, ctx: RouteContext) {
  return routeRequest(req, ctx);
}

export async function OPTIONS(req: NextRequest, ctx: RouteContext) {
  return routeRequest(req, ctx);
}
