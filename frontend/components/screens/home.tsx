"use client";
import { useRef, useState } from "react";
import { ChatScreen } from "./chat";
import { HomeInfoScreen } from "./home_info";

export { HomeInfoScreen };

export function HomeScreen({
  project,
  onNav,
  onMutate,
}: {
  project: any;
  onNav?: (screen: string) => void;
  onMutate?: () => void;
}) {
  // Draggable split percentage: defaults to 50% (half half)
  const [splitPct, setSplitPct] = useState(50);
  const containerRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);

  // Handle draggable divider
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    isDraggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDraggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const rawPct = ((moveEvent.clientX - rect.left) / rect.width) * 100;
      // Clamp between 20% and 80%
      const clamped = Math.max(20, Math.min(80, Math.round(rawPct)));
      setSplitPct(clamped);
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  };

  return (
    <div
      ref={containerRef}
      style={{
        display: "flex",
        width: "100%",
        height: "100%",
        minHeight: 0,
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* LEFT HALF: Stats & Info Page (from independent home_info.tsx) */}
      <div
        style={{
          width: `${splitPct}%`,
          height: "100%",
          minWidth: 280,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <HomeInfoScreen project={project} onNav={onNav} onMutate={onMutate} />
      </div>

      {/* DRAGGABLE DIVIDER (clean 1px hairline with transparent grab area) */}
      <div
        onMouseDown={handleMouseDown}
        style={{
          width: 1,
          flex: "none",
          position: "relative",
          background: "var(--line)",
          cursor: "col-resize",
          userSelect: "none",
          outline: "none",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            bottom: 0,
            left: -4,
            right: -4,
            cursor: "col-resize",
            zIndex: 10,
          }}
          title="Drag to resize panels"
        />
      </div>

      {/* RIGHT HALF: Chat Agent (from chat.tsx) */}
      <div
        style={{
          width: `${100 - splitPct}%`,
          height: "100%",
          minWidth: 280,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <ChatScreen project={project} onMutate={onMutate} />
      </div>
    </div>
  );
}
