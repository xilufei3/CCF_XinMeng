import { Button } from "@/components/ui/button";
import { useThreads } from "@/providers/Thread";
import { Message, Thread } from "@langchain/langgraph-sdk";
import { useEffect, useState } from "react";

import { getContentString } from "../utils";
import { useQueryState, parseAsBoolean } from "nuqs";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { LoaderCircle, PanelRightOpen, PanelRightClose, Trash2 } from "lucide-react";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { toast } from "sonner";

function shortThreadId(threadId: string): string {
  if (threadId.length <= 18) return threadId;
  return `${threadId.slice(0, 8)}...${threadId.slice(-6)}`;
}

function normalizeTitle(value: unknown, maxLength = 80): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1)}...`;
}

const REPORT_ID_TITLE_MAP: Record<string, string> = {
  camplus_txt: "示例报告",
};

function getReportThreadTitle(metadata: Record<string, unknown> | null): string | null {
  if (!metadata) return null;
  const sessionType = String(metadata.session_type ?? "").trim().toLowerCase();
  if (sessionType !== "report") return null;

  const explicitTitle = normalizeTitle(metadata.title);
  if (explicitTitle) return explicitTitle;

  const reportId = String(metadata.report_id ?? "").trim().toLowerCase();
  const mappedTitle = REPORT_ID_TITLE_MAP[reportId];
  if (mappedTitle) return `报告分析 · ${mappedTitle}`;

  if (reportId) return `报告分析 · ${reportId}`;
  return "报告分析";
}

function getThreadTitle(thread: Thread): string {
  const metadata =
    thread.metadata && typeof thread.metadata === "object"
      ? (thread.metadata as Record<string, unknown>)
      : null;
  const reportTitle = getReportThreadTitle(metadata);
  if (reportTitle) return reportTitle;

  const metadataTitle =
    normalizeTitle(metadata?.title) ?? normalizeTitle(metadata?.preview);
  if (metadataTitle) return metadataTitle;

  if (
    typeof thread.values === "object" &&
    thread.values &&
    "messages" in thread.values &&
    Array.isArray(thread.values.messages) &&
    thread.values.messages.length > 0
  ) {
    const firstMessage = thread.values.messages[0] as {
      content?: Message["content"];
      type?: string;
    };
    const fromMessage = normalizeTitle(getContentString(firstMessage.content ?? ""));
    if (fromMessage) return fromMessage;
  }

  return `对话 ${shortThreadId(thread.thread_id)}`;
}

function ThreadList({
  threads,
  deletingThreadId,
  onDeleteThread,
  onThreadClick,
}: {
  threads: Thread[];
  deletingThreadId?: string | null;
  onDeleteThread?: (thread: Thread) => void;
  onThreadClick?: (threadId: string) => void;
}) {
  const [threadId, setThreadId] = useQueryState("threadId");

  return (
    <div className="flex h-full w-full flex-col items-start justify-start gap-2 overflow-y-scroll [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-300 [&::-webkit-scrollbar-track]:bg-transparent">
      {threads.map((t) => {
        const itemText = getThreadTitle(t);
        const isSelected = t.thread_id === threadId;
        const isDeleting = t.thread_id === deletingThreadId;
        return (
          <div
            key={t.thread_id}
            className="group flex w-full items-center gap-1 px-1"
          >
            <Button
              variant="ghost"
              className={`h-auto min-h-10 flex-1 items-start justify-start py-2 text-left font-normal ${isSelected ? "bg-slate-100 hover:bg-slate-100" : ""}`}
              onClick={(e) => {
                e.preventDefault();
                onThreadClick?.(t.thread_id);
                if (t.thread_id === threadId) return;
                setThreadId(t.thread_id);
              }}
            >
              <p className="truncate text-ellipsis">{itemText}</p>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              disabled={isDeleting}
              className="shrink-0 text-gray-500 opacity-100 transition lg:opacity-0 lg:group-hover:opacity-100 hover:text-red-600 hover:bg-red-50 disabled:opacity-100"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onDeleteThread?.(t);
              }}
            >
              {isDeleting ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <Trash2 className="size-4" />
              )}
            </Button>
          </div>
        );
      })}
    </div>
  );
}

function ThreadHistoryLoading() {
  return (
    <div className="flex h-full w-full flex-col items-start justify-start gap-2 overflow-y-scroll [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-300 [&::-webkit-scrollbar-track]:bg-transparent">
      {Array.from({ length: 30 }).map((_, i) => (
        <Skeleton
          key={`skeleton-${i}`}
          className="h-10 w-[280px]"
        />
      ))}
    </div>
  );
}

export default function ThreadHistory() {
  const isLargeScreen = useMediaQuery("(min-width: 1024px)");
  const [threadId, setThreadId] = useQueryState("threadId");
  const [chatHistoryOpen, setChatHistoryOpen] = useQueryState(
    "chatHistoryOpen",
    parseAsBoolean.withDefault(false),
  );
  const [deletingThreadId, setDeletingThreadId] = useState<string | null>(null);

  const {
    getThreads,
    deleteThread,
    threads,
    setThreads,
    threadsLoading,
    setThreadsLoading,
  } = useThreads();

  useEffect(() => {
    if (typeof window === "undefined") return;
    setThreadsLoading(true);
    getThreads()
      .then(setThreads)
      .catch(console.error)
      .finally(() => setThreadsLoading(false));
  }, []);

  const handleDeleteThread = async (thread: Thread) => {
    if (deletingThreadId) return;
    if (typeof window !== "undefined") {
      const ok = window.confirm("确认从历史记录中删除这个对话吗？");
      if (!ok) return;
    }
    const previousThreads = threads;
    setDeletingThreadId(thread.thread_id);
    setThreads((prev) => prev.filter((item) => item.thread_id !== thread.thread_id));
    if (thread.thread_id === threadId) {
      setThreadId(null);
    }
    try {
      await deleteThread(thread.thread_id);
      toast.success("已删除对话");
    } catch (err) {
      setThreads(previousThreads);
      toast.error("删除失败", {
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDeletingThreadId(null);
    }
  };

  return (
    <>
      <div className="shadow-inner-right hidden h-screen w-[300px] shrink-0 flex-col items-start justify-start gap-6 border-r-[1px] border-[#f1cda8] bg-white/80 lg:flex">
        <div className="flex w-full items-center justify-between px-4 pt-1.5">
          <Button
            className="hover:bg-gray-100"
            variant="ghost"
            onClick={() => setChatHistoryOpen((p) => !p)}
          >
            {chatHistoryOpen ? (
              <PanelRightOpen className="size-5" />
            ) : (
              <PanelRightClose className="size-5" />
            )}
          </Button>
          <h1 className="font-display text-xl tracking-tight text-[#8c4a00]">
            对话历史
          </h1>
        </div>
        {threadsLoading ? (
          <ThreadHistoryLoading />
        ) : (
          <ThreadList
            threads={threads}
            deletingThreadId={deletingThreadId}
            onDeleteThread={handleDeleteThread}
          />
        )}
      </div>
      <div className="lg:hidden">
        <Sheet
          open={!!chatHistoryOpen && !isLargeScreen}
          onOpenChange={(open) => {
            if (isLargeScreen) return;
            setChatHistoryOpen(open);
          }}
        >
          <SheetContent
            side="left"
            className="flex lg:hidden"
          >
            <SheetHeader>
              <SheetTitle>对话历史</SheetTitle>
            </SheetHeader>
            <ThreadList
              threads={threads}
              deletingThreadId={deletingThreadId}
              onDeleteThread={handleDeleteThread}
              onThreadClick={() => setChatHistoryOpen((o) => !o)}
            />
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}
