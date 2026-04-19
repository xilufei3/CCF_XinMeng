import { v4 as uuidv4 } from "uuid";
import {
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { useStreamContext } from "@/providers/Stream";
import { Button } from "../ui/button";
import { Checkpoint, Message } from "@langchain/langgraph-sdk";
import { AssistantMessage, AssistantMessageLoading } from "./messages/ai";
import { HumanMessage } from "./messages/human";
import {
  DO_NOT_RENDER_ID_PREFIX,
  ensureToolCallsHaveResponses,
} from "@/lib/ensure-tool-responses";
import { TooltipIconButton } from "./tooltip-icon-button";
import {
  ArrowDown,
  LoaderCircle,
  PanelRightOpen,
  PanelRightClose,
  SquarePen,
  Sparkles,
  XIcon,
  FileText,
} from "lucide-react";
import { useQueryState, parseAsBoolean } from "nuqs";
import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import ThreadHistory from "./history";
import { toast } from "sonner";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { Label } from "../ui/label";
import { Switch } from "../ui/switch";
import { useFileUpload } from "@/hooks/use-file-upload";
import { ContentBlocksPreview } from "./ContentBlocksPreview";
import {
  useArtifactOpen,
  ArtifactContent,
  ArtifactTitle,
  useArtifactContext,
} from "./artifact";
import { useThreads } from "@/providers/Thread";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "../ui/sheet";

const STARTER_ACTIONS = [
  {
    question: "孩子写字总出错,是读写障碍吗?",
  },
  {
    question: "怎么判断孩子是不是读写障碍?",
  },
  {
    question: "怎么联系星萌乐读?",
  },
];
const REPORT_INIT_COMMAND = "[[REPORT_SESSION_INIT::camplus_txt]]";

type ReportDocument = {
  thread_id: string;
  session_type: string;
  report_id?: string | null;
  report_text: string;
  title?: string;
};

function StickyToBottomContent(props: {
  content: ReactNode;
  footer?: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const context = useStickToBottomContext();
  return (
    <div
      ref={context.scrollRef}
      style={{ width: "100%", height: "100%" }}
      className={props.className}
    >
      <div
        ref={context.contentRef}
        className={props.contentClassName}
      >
        {props.content}
      </div>

      {props.footer}
    </div>
  );
}

function ScrollToBottom(props: { className?: string }) {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();

  if (isAtBottom) return null;
  return (
    <Button
      variant="outline"
      className={props.className}
      onClick={() => scrollToBottom()}
    >
      <ArrowDown className="h-4 w-4" />
      <span>回到底部</span>
    </Button>
  );
}

export function Thread() {
  const [artifactContext, setArtifactContext] = useArtifactContext();
  const [artifactOpen, closeArtifact] = useArtifactOpen();
  const { threads } = useThreads();

  const [threadId, _setThreadId] = useQueryState("threadId");
  const [chatHistoryOpen, setChatHistoryOpen] = useQueryState(
    "chatHistoryOpen",
    parseAsBoolean.withDefault(false),
  );
  const [webSearchEnabled, setWebSearchEnabled] = useQueryState(
    "webSearchEnabled",
    parseAsBoolean.withDefault(false),
  );
  const [input, setInput] = useState("");
  const [pendingReportStart, setPendingReportStart] = useState(false);
  const [reportPanelOpen, setReportPanelOpen] = useState(false);
  const [reportDoc, setReportDoc] = useState<ReportDocument | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const {
    contentBlocks,
    setContentBlocks,
    dropRef,
    removeBlock,
    resetBlocks: _resetBlocks,
    dragOver,
    handlePaste,
  } = useFileUpload();
  const [firstTokenReceived, setFirstTokenReceived] = useState(false);
  const isLargeScreen = useMediaQuery("(min-width: 1024px)");

  const stream = useStreamContext();
  const messages = stream.messages;
  const isLoading = stream.isLoading;

  const lastError = useRef<string | undefined>(undefined);

  const setThreadId = (id: string | null) => {
    _setThreadId(id);

    // close artifact and reset artifact context
    closeArtifact();
    setArtifactContext({});
    setReportPanelOpen(false);
    setReportDoc(null);
    setReportError(null);
  };

  const currentThread = useMemo(() => {
    if (!threadId) return null;
    return threads.find((item) => item.thread_id === threadId) ?? null;
  }, [threadId, threads]);

  const isReportSession = useMemo(() => {
    if (!currentThread) return false;
    const metadata =
      currentThread.metadata && typeof currentThread.metadata === "object"
        ? (currentThread.metadata as Record<string, unknown>)
        : null;
    return (
      String(metadata?.session_type ?? "").trim().toLowerCase() === "report"
    );
  }, [currentThread]);

  const hasReportInitMessage = useMemo(() => {
    return messages.some((message) => {
      if (message.type !== "human") return false;
      const content = message.content;
      if (typeof content === "string") {
        return content.includes(REPORT_INIT_COMMAND);
      }
      if (!Array.isArray(content)) return false;
      return content.some((part) => {
        if (!part || typeof part !== "object") return false;
        if (!("type" in part) || !("text" in part)) return false;
        return (
          (part as { type?: string }).type === "text" &&
          typeof (part as { text?: unknown }).text === "string" &&
          String((part as { text?: unknown }).text).includes(REPORT_INIT_COMMAND)
        );
      });
    });
  }, [messages]);

  const canOpenReport = !!threadId && (isReportSession || hasReportInitMessage);
  const sidePanelDesktopOpen = artifactOpen || (isLargeScreen && reportPanelOpen);

  const loadReportDocument = useCallback(async (targetThreadId: string) => {
    const response = await fetch(
      `/api/threads/${encodeURIComponent(targetThreadId)}/report`,
      {
        method: "GET",
        cache: "no-store",
      },
    );
    if (!response.ok) {
      let errorMessage = `加载报告失败 (${response.status})`;
      try {
        const payload = (await response.json()) as {
          error?: unknown;
          message?: unknown;
        };
        if (typeof payload?.message === "string" && payload.message.trim()) {
          errorMessage = payload.message.trim();
        } else if (typeof payload?.error === "string" && payload.error.trim()) {
          errorMessage = payload.error.trim();
        }
      } catch {
        // no-op
      }
      throw new Error(errorMessage);
    }
    return (await response.json()) as ReportDocument;
  }, []);

  const handleOpenReport = useCallback(async () => {
    if (!threadId || reportLoading) return;
    closeArtifact();
    setReportPanelOpen(true);
    if (reportDoc && reportDoc.thread_id === threadId) {
      setReportError(null);
      return;
    }
    setReportLoading(true);
    setReportError(null);
    try {
      const next = await loadReportDocument(threadId);
      setReportDoc(next);
    } catch (err) {
      const message = err instanceof Error ? err.message : "加载报告失败";
      setReportError(message);
      setReportDoc(null);
    } finally {
      setReportLoading(false);
    }
  }, [threadId, reportLoading, reportDoc, loadReportDocument, closeArtifact]);

  const closeReportPanel = useCallback(() => {
    setReportPanelOpen(false);
  }, []);

  useEffect(() => {
    if (!stream.error) {
      lastError.current = undefined;
      return;
    }
    try {
      const message = (stream.error as any).message;
      if (!message || lastError.current === message) {
        // Message has already been logged. do not modify ref, return early.
        return;
      }

      // Message is defined, and it has not been logged yet. Save it, and send the error
      lastError.current = message;
      toast.error("请求失败，请稍后再试", {
        description: (
          <p>
            <strong>错误信息:</strong> <code>{message}</code>
          </p>
        ),
        richColors: true,
        closeButton: true,
      });
    } catch {
      // no-op
    }
  }, [stream.error]);

  // TODO: this should be part of the useStream hook
  const prevMessageLength = useRef(0);
  useEffect(() => {
    if (
      messages.length !== prevMessageLength.current &&
      messages?.length &&
      messages[messages.length - 1].type === "ai"
    ) {
      setFirstTokenReceived(true);
    }

    prevMessageLength.current = messages.length;
  }, [messages]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if ((input.trim().length === 0 && contentBlocks.length === 0) || isLoading)
      return;
    setFirstTokenReceived(false);

    const newHumanMessage: Message = {
      id: uuidv4(),
      type: "human",
      content: [
        ...(input.trim().length > 0 ? [{ type: "text", text: input }] : []),
        ...contentBlocks,
      ] as Message["content"],
    };

    const toolMessages = ensureToolCallsHaveResponses(stream.messages);

    const context = {
      ...artifactContext,
      web_search_enabled: webSearchEnabled ?? false,
    };

    stream.submit(
      { messages: [...toolMessages, newHumanMessage], context },
      {
        streamMode: ["values"],
        streamSubgraphs: true,
        streamResumable: true,
        optimisticValues: (prev) => ({
          ...prev,
          context,
          messages: [
            ...(prev.messages ?? []),
            ...toolMessages,
            newHumanMessage,
          ],
        }),
      },
    );

    setInput("");
    setContentBlocks([]);
  };

  const handleStartReportSession = () => {
    if (isLoading) return;
    setFirstTokenReceived(false);
    setInput("");
    setContentBlocks([]);
    setPendingReportStart(true);
    setThreadId(null);
  };

  const handleRegenerate = (
    parentCheckpoint: Checkpoint | null | undefined,
  ) => {
    // Do this so the loading state is correct
    prevMessageLength.current = prevMessageLength.current - 1;
    setFirstTokenReceived(false);
    stream.submit(undefined, {
      checkpoint: parentCheckpoint,
      streamMode: ["values"],
      streamSubgraphs: true,
      streamResumable: true,
    });
  };

  const chatStarted = !!threadId || !!messages.length;
  const hasNoAIOrToolMessages = !messages.find(
    (m) => m.type === "ai" || m.type === "tool",
  );

  useEffect(() => {
    if (!threadId) {
      setReportPanelOpen(false);
      setReportDoc(null);
      setReportError(null);
      setReportLoading(false);
    }
  }, [threadId]);

  useEffect(() => {
    if (artifactOpen && reportPanelOpen) {
      setReportPanelOpen(false);
    }
  }, [artifactOpen, reportPanelOpen]);

  useEffect(() => {
    if (!pendingReportStart || threadId !== null) {
      return;
    }

    const context = {
      ...artifactContext,
      web_search_enabled: webSearchEnabled ?? false,
    };
    const hiddenInitMessage: Message = {
      id: `${DO_NOT_RENDER_ID_PREFIX}${uuidv4()}`,
      type: "human",
      content: [{ type: "text", text: REPORT_INIT_COMMAND }] as Message["content"],
    };
    const toolMessages = ensureToolCallsHaveResponses(stream.messages);
    stream.submit(
      { messages: [...toolMessages, hiddenInitMessage], context },
      {
        streamMode: ["values"],
        streamSubgraphs: true,
        streamResumable: true,
        optimisticValues: (prev) => ({
          ...prev,
          context,
          messages: [
            ...(prev.messages ?? []),
            ...toolMessages,
            hiddenInitMessage,
          ],
        }),
      },
    );
    setPendingReportStart(false);
  }, [pendingReportStart, threadId, artifactContext, stream, webSearchEnabled]);

  return (
    <div className="flex h-screen w-full overflow-hidden">
      <div className="relative hidden lg:flex">
        <motion.div
          className="absolute z-20 h-full overflow-hidden border-r border-white/50 bg-white/85 backdrop-blur"
          style={{ width: 300 }}
          animate={
            isLargeScreen
              ? { x: chatHistoryOpen ? 0 : -300 }
              : { x: chatHistoryOpen ? 0 : -300 }
          }
          initial={{ x: -300 }}
          transition={
            isLargeScreen
              ? { type: "spring", stiffness: 300, damping: 30 }
              : { duration: 0 }
          }
        >
          <div
            className="relative h-full"
            style={{ width: 300 }}
          >
            <ThreadHistory />
          </div>
        </motion.div>
      </div>

      <div
        className={cn(
          "grid w-full grid-cols-[1fr_0fr] transition-all duration-500",
          sidePanelDesktopOpen && "grid-cols-[3fr_2fr]",
        )}
      >
        <motion.div
          className={cn(
            "relative flex min-w-0 flex-1 flex-col overflow-hidden",
            !chatStarted && "grid-rows-[1fr]",
          )}
          layout={isLargeScreen}
          animate={{
            marginLeft: chatHistoryOpen ? (isLargeScreen ? 300 : 0) : 0,
            width: chatHistoryOpen
              ? isLargeScreen
                ? "calc(100% - 300px)"
                : "100%"
              : "100%",
          }}
          transition={
            isLargeScreen
              ? { type: "spring", stiffness: 300, damping: 30 }
              : { duration: 0 }
          }
        >
          <div className="pointer-events-none absolute inset-x-0 top-0 h-36 bg-gradient-to-b from-[#ffe5cb]/80 via-[#fff8ef]/30 to-transparent" />

          {!chatStarted && (
            <div className="absolute top-0 left-0 z-10 flex w-full items-center justify-between gap-3 px-4 pt-4">
              <div>
                {(!chatHistoryOpen || !isLargeScreen) && (
                  <Button
                    className="hover:bg-orange-50"
                    variant="ghost"
                    onClick={() => setChatHistoryOpen((p) => !p)}
                  >
                    {chatHistoryOpen ? (
                      <PanelRightOpen className="size-5" />
                    ) : (
                      <PanelRightClose className="size-5" />
                    )}
                  </Button>
                )}
              </div>
              <div className="hidden items-center gap-2 rounded-full border border-[#ffd6ab] bg-white/90 px-4 py-2 text-sm text-[#9a4f00] shadow-sm md:flex">
                <Sparkles className="size-4" />
                <span className="font-medium">星萌乐读 AI 陪伴顾问</span>
              </div>
            </div>
          )}

          {chatStarted && (
            <div className="relative z-10 flex items-center justify-between gap-3 p-3">
              <div className="relative flex items-center justify-start gap-2">
                <div className="absolute left-0 z-10">
                  {(!chatHistoryOpen || !isLargeScreen) && (
                    <Button
                      className="hover:bg-orange-50"
                      variant="ghost"
                      onClick={() => setChatHistoryOpen((p) => !p)}
                    >
                      {chatHistoryOpen ? (
                        <PanelRightOpen className="size-5" />
                      ) : (
                        <PanelRightClose className="size-5" />
                      )}
                    </Button>
                  )}
                </div>
                <motion.button
                  className="flex cursor-pointer items-center gap-2 rounded-full border border-[#ffd6ab] bg-white px-4 py-2 shadow-sm"
                  onClick={() => setThreadId(null)}
                  animate={{
                    marginLeft: !chatHistoryOpen ? 48 : 0,
                  }}
                  transition={{
                    type: "spring",
                    stiffness: 300,
                    damping: 30,
                  }}
                >
                  <div className="rounded-full bg-[#fff2e3] p-1.5 text-[#ff8a00]">
                    <Sparkles className="size-4" />
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-semibold tracking-tight text-[#8a4a00]">
                      星萌乐读
                    </p>
                    <p className="text-xs text-[#b9772c]">家长沟通助手</p>
                  </div>
                </motion.button>
              </div>

              <div className="flex items-center gap-2">
                {canOpenReport && (
                  <TooltipIconButton
                    size="lg"
                    className="p-4"
                    tooltip="查看报告原文"
                    variant="ghost"
                    onClick={handleOpenReport}
                  >
                    <FileText className="size-5" />
                  </TooltipIconButton>
                )}
                <TooltipIconButton
                  size="lg"
                  className="p-4"
                  tooltip="报告分析(示例)"
                  variant="ghost"
                  onClick={handleStartReportSession}
                >
                  <Sparkles className="size-5" />
                </TooltipIconButton>
                <TooltipIconButton
                  size="lg"
                  className="p-4"
                  tooltip="新建对话"
                  variant="ghost"
                  onClick={() => setThreadId(null)}
                >
                  <SquarePen className="size-5" />
                </TooltipIconButton>
              </div>

              <div className="from-background to-background/0 absolute inset-x-0 top-full h-5 bg-gradient-to-b" />
            </div>
          )}

          <StickToBottom className="relative flex-1 overflow-hidden">
            <StickyToBottomContent
              className={cn(
                "absolute inset-0 overflow-y-scroll px-4 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-[#efbf95] [&::-webkit-scrollbar-track]:bg-transparent",
                !chatStarted && "mt-[20vh] flex flex-col items-stretch",
                chatStarted && "grid grid-rows-[1fr_auto]",
              )}
              contentClassName="mx-auto flex w-full max-w-3xl flex-col gap-4 pt-8 pb-16"
              content={
                <>
                  {messages
                    .filter((m) => !m.id?.startsWith(DO_NOT_RENDER_ID_PREFIX))
                    .map((message, index) =>
                      message.type === "human" ? (
                        <HumanMessage
                          key={message.id || `${message.type}-${index}`}
                          message={message}
                          isLoading={isLoading}
                        />
                      ) : (
                        <AssistantMessage
                          key={message.id || `${message.type}-${index}`}
                          message={message}
                          isLoading={isLoading}
                          handleRegenerate={handleRegenerate}
                        />
                      ),
                    )}
                  {/* Special rendering case where there are no AI/tool messages, but there is an interrupt.
                    We need to render it outside of the messages list, since there are no messages to render */}
                  {hasNoAIOrToolMessages && !!stream.interrupt && (
                    <AssistantMessage
                      key="interrupt-msg"
                      message={undefined}
                      isLoading={isLoading}
                      handleRegenerate={handleRegenerate}
                    />
                  )}
                  {isLoading && !firstTokenReceived && (
                    <AssistantMessageLoading />
                  )}
                </>
              }
              footer={
                <div className="sticky bottom-0 flex flex-col items-center gap-6 bg-gradient-to-b from-transparent via-[#fff8f0] to-[#fff8f0] pt-4">
                  {!chatStarted && (
                    <div className="w-full max-w-3xl rounded-3xl border border-[#ffd9b4] bg-white/90 p-6 shadow-[0_12px_40px_rgba(246,147,45,0.16)] backdrop-blur">
                      <div className="flex items-start gap-3">
                        <div className="rounded-2xl bg-[#fff1df] p-2 text-[#ff8a00]">
                          <Sparkles className="size-5" />
                        </div>
                        <div>
                          <h1 className="font-display text-2xl text-[#8c4a00]">
                            星萌乐读
                          </h1>
                          <p className="mt-1 text-sm text-[#7f6a52]">
                            为担心孩子读写困难的家长，提供可执行、可落地的沟通支持。
                          </p>
                        </div>
                      </div>

                      <div className="mt-5 grid gap-3 md:grid-cols-3">
                        {STARTER_ACTIONS.map((item) => (
                          <button
                            key={item.question}
                            type="button"
                            className="rounded-2xl border border-[#ffe1c2] bg-[#fffbf6] p-3 text-left transition hover:-translate-y-0.5 hover:border-[#ffbf7a] hover:shadow-sm"
                            onClick={() => setInput(item.question)}
                          >
                            <p className="text-sm leading-6 font-medium text-[#8c4a00]">
                              {item.question}
                            </p>
                          </button>
                        ))}
                      </div>
                      <div className="mt-4">
                        <Button
                          type="button"
                          variant="outline"
                          className="w-full border-[#ffbf7a] bg-[#fff8ef] text-[#8c4a00] hover:bg-[#fff1e0]"
                          onClick={handleStartReportSession}
                        >
                          报告分析（示例报告）
                        </Button>
                      </div>
                    </div>
                  )}

                  <ScrollToBottom className="animate-in fade-in-0 zoom-in-95 absolute bottom-full left-1/2 mb-4 -translate-x-1/2 border-[#f3cb9f] bg-white text-[#8a4a00]" />

                  <div
                    ref={dropRef}
                    className={cn(
                      "relative z-10 mx-auto mb-8 w-full max-w-3xl rounded-3xl border bg-white/95 shadow-[0_12px_28px_rgba(246,147,45,0.13)] transition-all",
                      dragOver
                        ? "border-2 border-dotted border-[#ff9800]"
                        : "border-[#f5d1b2]",
                    )}
                  >
                    <form
                      onSubmit={handleSubmit}
                      className="mx-auto grid max-w-3xl grid-rows-[1fr_auto] gap-2"
                    >
                      <ContentBlocksPreview
                        blocks={contentBlocks}
                        onRemove={removeBlock}
                      />
                      <textarea
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onPaste={handlePaste}
                        onKeyDown={(e) => {
                          if (
                            e.key === "Enter" &&
                            !e.shiftKey &&
                            !e.metaKey &&
                            !e.nativeEvent.isComposing
                          ) {
                            e.preventDefault();
                            const el = e.target as HTMLElement | undefined;
                            const form = el?.closest("form");
                            form?.requestSubmit();
                          }
                        }}
                        placeholder="请输入您孩子近期在阅读、拼写、书写上的具体表现..."
                        className="field-sizing-content resize-none border-none bg-transparent p-4 pb-0 text-[15px] leading-7 shadow-none ring-0 outline-none focus:ring-0 focus:outline-none"
                      />

                      <div className="flex flex-wrap items-center gap-4 p-3 pt-2">
                        <div className="flex items-center space-x-2">
                          <Switch
                            id="web-search-enabled"
                            checked={webSearchEnabled ?? false}
                            onCheckedChange={setWebSearchEnabled}
                          />
                          <Label
                            htmlFor="web-search-enabled"
                            className="text-sm text-[#7c6b58]"
                          >
                            联网搜索
                          </Label>
                        </div>

                        {stream.isLoading ? (
                          <Button
                            key="stop"
                            onClick={() => stream.stop()}
                            className="ml-auto bg-[#8a4a00] hover:bg-[#743d00]"
                          >
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                            停止生成
                          </Button>
                        ) : (
                          <Button
                            type="submit"
                            className="ml-auto bg-[#ff8a00] text-white shadow-md transition-all hover:bg-[#ea7d00]"
                            disabled={
                              isLoading ||
                              (!input.trim() && contentBlocks.length === 0)
                            }
                          >
                            发送
                          </Button>
                        )}
                      </div>
                    </form>
                  </div>
                </div>
              }
            />
          </StickToBottom>
        </motion.div>

        <div className="relative flex flex-col border-l border-[#f6d6b6] bg-white/70">
          <div className="absolute inset-0 flex min-w-[30vw] flex-col">
            {reportPanelOpen ? (
              <>
                <div className="grid grid-cols-[1fr_auto] border-b border-[#f6d6b6] p-4">
                  <div className="truncate overflow-hidden text-sm font-semibold text-[#8a4a00]">
                    {reportDoc?.title || "筛查报告原文"}
                  </div>
                  <button
                    onClick={closeReportPanel}
                    className="cursor-pointer"
                  >
                    <XIcon className="size-5" />
                  </button>
                </div>
                <div className="relative flex-grow overflow-y-auto p-4">
                  {reportLoading && (
                    <div className="flex items-center gap-2 text-sm text-[#8a4a00]">
                      <LoaderCircle className="size-4 animate-spin" />
                      <span>报告加载中...</span>
                    </div>
                  )}
                  {!reportLoading && reportError && (
                    <div className="rounded-xl border border-[#ffd6ab] bg-[#fff8ef] p-3 text-sm text-[#8a4a00]">
                      {reportError}
                    </div>
                  )}
                  {!reportLoading && !reportError && reportDoc?.report_text && (
                    <pre className="whitespace-pre-wrap break-words text-sm leading-6 text-[#5a3a1a]">
                      {reportDoc.report_text}
                    </pre>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="grid grid-cols-[1fr_auto] border-b border-[#f6d6b6] p-4">
                  <ArtifactTitle className="truncate overflow-hidden" />
                  <button
                    onClick={closeArtifact}
                    className="cursor-pointer"
                  >
                    <XIcon className="size-5" />
                  </button>
                </div>
                <ArtifactContent className="relative flex-grow" />
              </>
            )}
          </div>
        </div>
      </div>

      <div className="lg:hidden">
        <Sheet
          open={reportPanelOpen && !isLargeScreen}
          onOpenChange={(open) => {
            if (isLargeScreen) return;
            setReportPanelOpen(open);
          }}
        >
          <SheetContent
            side="right"
            className="w-[92vw] p-0 sm:max-w-xl"
          >
            <SheetHeader className="border-b border-[#f6d6b6]">
              <SheetTitle className="text-[#8a4a00]">
                {reportDoc?.title || "筛查报告原文"}
              </SheetTitle>
            </SheetHeader>
            <div className="flex-1 overflow-y-auto p-4">
              {reportLoading && (
                <div className="flex items-center gap-2 text-sm text-[#8a4a00]">
                  <LoaderCircle className="size-4 animate-spin" />
                  <span>报告加载中...</span>
                </div>
              )}
              {!reportLoading && reportError && (
                <div className="rounded-xl border border-[#ffd6ab] bg-[#fff8ef] p-3 text-sm text-[#8a4a00]">
                  {reportError}
                </div>
              )}
              {!reportLoading && !reportError && reportDoc?.report_text && (
                <pre className="whitespace-pre-wrap break-words text-sm leading-6 text-[#5a3a1a]">
                  {reportDoc.report_text}
                </pre>
              )}
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </div>
  );
}
