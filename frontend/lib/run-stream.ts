/* Shared SSE execution-stream logic for Workflow test panel and Playground. */
import { openSSE, type SSEFrame } from "./api";
import { ReplyAccumulator, type Part, type ComponentInstance } from "./chat-parts";

export interface StreamActivity {
  id: string;
  kind: string;
  name: string;
  done: boolean;
  error?: boolean;
}

export interface StreamCallbacks {
  onText?: (fullText: string, liveParts: Part[]) => void;
  onNodeStep?: (nodeId: string) => void;
  onActivity?: (activity: StreamActivity) => void;
  onComponent?: (comp: ComponentInstance, liveParts: Part[]) => void;
  onInterrupt?: (payload: any) => void;
  onDone?: (meter: { tokens: number; cost: number; answer?: string }) => void;
  onError?: (errMessage: string) => void;
}

export async function runWorkflowSSE(
  streamUrl: string,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<{ answer: string; interrupted: boolean; parts: Part[] }> {
  const acc = new ReplyAccumulator();
  let interrupted = false;
  let finalAnswer = "";

  await openSSE(
    streamUrl,
    (f: SSEFrame) => {
      if (f.event === "messages" && f.data?.content) {
        acc.addText(f.data.content);
        callbacks.onText?.(acc.text, acc.parts({ streaming: true }));
      } else if ((f.event === "node_start" || f.event === "updates") && f.data) {
        const node = f.event === "node_start" ? f.data.node : Object.keys(f.data || {})[0];
        if (node) callbacks.onNodeStep?.(node);
      } else if (f.event === "activity" && f.data?.id) {
        const a = f.data;
        if (a.phase === "start") {
          callbacks.onActivity?.({ id: a.id, kind: a.kind, name: a.name, done: false });
        } else if (a.phase === "end") {
          callbacks.onActivity?.({ id: a.id, kind: a.kind, name: a.name, done: true, error: !!a.error });
        }
      } else if (f.event === "custom" && f.data?.channel === "component" && f.data?.payload) {
        acc.addComponent(f.data.payload as ComponentInstance);
        callbacks.onComponent?.(f.data.payload as ComponentInstance, acc.parts({ streaming: true }));
      } else if (f.event === "done") {
        finalAnswer = f.data?.answer || "";
        callbacks.onDone?.({
          tokens: f.data?.total_tokens ?? 0,
          cost: f.data?.total_cost_usd ?? 0,
          answer: finalAnswer,
        });
      } else if (f.event === "interrupt") {
        interrupted = true;
        callbacks.onInterrupt?.(f.data);
      } else if (f.event === "error") {
        finalAnswer = `⚠ ${f.data?.message || "run failed"}`;
        callbacks.onError?.(f.data?.message || "run failed");
      }
    },
    { signal },
  );

  return {
    answer: finalAnswer,
    interrupted,
    parts: acc.parts(),
  };
}
