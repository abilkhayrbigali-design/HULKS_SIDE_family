import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import type { PanelImperativeHandle } from "react-resizable-panels";
export type Pane = "queue" | "transcript" | "quality";
interface WorkspaceState {
  activePane: Pane;
  setActivePane: (pane: Pane) => void;
  narrow: boolean;
  queueCollapsed: boolean;
  qualityCollapsed: boolean;
  toggleQueue: () => void;
  toggleQuality: () => void;
  queueRef: RefObject<PanelImperativeHandle | null>;
  qualityRef: RefObject<PanelImperativeHandle | null>;
  queueRevision: number;
  refreshQueue: () => void;
}
const Context = createContext<WorkspaceState | null>(null);
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [activePane, setActivePane] = useState<Pane>("queue");
  const [narrow, setNarrow] = useState(
    () => matchMedia("(max-width: 1000px)").matches,
  );
  const [queueCollapsed, setQueueCollapsed] = useState(false);
  const [qualityCollapsed, setQualityCollapsed] = useState(false);
  const [queueRevision, setRevision] = useState(0);
  const queueRef = useRef<PanelImperativeHandle | null>(null),
    qualityRef = useRef<PanelImperativeHandle | null>(null);
  useEffect(() => {
    const media = matchMedia("(max-width: 1000px)");
    const change = () => setNarrow(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  const toggleQueue = () => {
    if (narrow) {
      setActivePane("queue");
      return;
    }
    const ref = queueRef.current;
    if (!ref) return;
    if (ref.isCollapsed()) {
      ref.expand();
      setQueueCollapsed(false);
    } else {
      ref.collapse();
      setQueueCollapsed(true);
    }
  };
  const toggleQuality = () => {
    if (narrow) {
      setActivePane("quality");
      return;
    }
    const ref = qualityRef.current;
    if (!ref) return;
    if (ref.isCollapsed()) {
      ref.expand();
      setQualityCollapsed(false);
    } else {
      ref.collapse();
      setQualityCollapsed(true);
    }
  };
  return (
    <Context.Provider
      value={{
        activePane,
        setActivePane,
        narrow,
        queueCollapsed,
        qualityCollapsed,
        toggleQueue,
        toggleQuality,
        queueRef,
        qualityRef,
        queueRevision,
        refreshQueue: () => setRevision((v) => v + 1),
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useWorkspace() {
  const context = useContext(Context);
  if (!context) throw new Error("Workspace context is unavailable");
  return context;
}
