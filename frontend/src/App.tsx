import { useEffect, useState } from "react";
import {
  CheckCheck,
  ClipboardList,
  Inbox,
  Layers,
  Menu,
  Moon,
  PanelLeftClose,
  PanelRightClose,
  Sun,
  MessagesSquare,
  ShieldCheck,
} from "lucide-react";
import { Button } from "./components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./components/ui/tooltip";
import { Separator } from "./components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "./components/ui/sheet";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "./components/ui/resizable";
import type { Layout } from "react-resizable-panels";
import { Conversations } from "./features/Conversations";
import { ConversationView } from "./features/ConversationView";
import { Checklists } from "./features/Checklists";
import { Batches } from "./features/Batches";
import { WorkspaceProvider, useWorkspace } from "./workspace/context";
import { BatchProvider } from "./workspace/batches";
import { Empty } from "./ui";
function route() {
  const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
  return {
    path: path || "/dialogues",
    evaluation: new URLSearchParams(query).get("evaluation"),
  };
}
function storedTheme() {
  try {
    return localStorage.getItem("cqa.theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}
export function App() {
  const [current, setCurrent] = useState(route);
  const [lastWorkspace, setLastWorkspace] = useState(() =>
    location.hash.startsWith("#/dialogues/") ? location.hash : "#/dialogues",
  );
  const [theme, setTheme] = useState(storedTheme);
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const onHash = () => {
      const next = route();
      setCurrent(next);
      if (next.path.startsWith("/dialogues"))
        setLastWorkspace(location.hash || "#/dialogues");
      setMobile(false);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
    try {
      localStorage.setItem("cqa.theme", theme);
    } catch {
      /* Preferences are optional. */
    }
  }, [theme]);
  const id = current.path.match(/^\/dialogues\/([^/]+)$/)?.[1];
  const checklist = current.path === "/checklists";
  const batches = current.path === "/batches";
  const documentPage = checklist || batches;
  const dialogueLink = documentPage ? lastWorkspace : "#/dialogues";
  const navigation = (
    <>
      <a className={!documentPage ? "active" : ""} href={dialogueLink}>
        <Inbox size={18} />
        <span>Диалоги</span>
      </a>
      <a className={checklist ? "active" : ""} href="#/checklists">
        <ClipboardList size={18} />
        <span>Чек-листы</span>
      </a>
      <a className={batches ? "active" : ""} href="#/batches">
        <Layers size={18} />
        <span>Пакетная оценка</span>
      </a>
    </>
  );
  return (
    <TooltipProvider delayDuration={350}>
      <WorkspaceProvider>
        <BatchProvider>
        <div className="app-shell">
          <a
            href="#main"
            className="skip-link"
            onClick={(e) => {
              e.preventDefault();
              document.getElementById("main")?.focus();
            }}
          >
            К содержимому
          </a>
          <header className="app-header">
            <div className="header-brand">
              <span className="brand-mark">
                <CheckCheck size={21} />
              </span>
              <strong>HULK’S FAMILY</strong>
              <Separator orientation="vertical" />
              <span className="workspace-caption">Quality workspace</span>
            </div>
            <div className="header-actions">
              <span className="environment">
                <ShieldCheck size={14} />
                Контроль качества
              </span>
              <IconButton
                label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              >
                {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
              </IconButton>
              <Button
                variant="ghost"
                size="icon-sm"
                className="mobile-menu"
                onClick={() => setMobile(true)}
                aria-label="Открыть навигацию"
              >
                <Menu size={18} />
              </Button>
            </div>
          </header>
          <aside className="sidebar" aria-label="Основная навигация">
            <a
              className="rail-brand"
              href="#/dialogues"
              aria-label="HULK’S FAMILY"
            >
              <CheckCheck size={22} />
            </a>
            <nav>
              {[
                ["Диалоги", dialogueLink, Inbox, !documentPage],
                ["Чек-листы", "#/checklists", ClipboardList, checklist],
                ["Пакетная оценка", "#/batches", Layers, batches],
              ].map(([label, href, Icon, active]) => {
                const Glyph = Icon as typeof Inbox;
                return (
                  <Tooltip key={String(href)}>
                    <TooltipTrigger asChild>
                      <a
                        href={String(href)}
                        aria-label={String(label)}
                        className={active ? "rail-link active" : "rail-link"}
                      >
                        <Glyph size={20} />
                      </a>
                    </TooltipTrigger>
                    <TooltipContent side="right">
                      {String(label)}
                    </TooltipContent>
                  </Tooltip>
                );
              })}
            </nav>
            <span className="avatar" aria-label="Команда HULK’S FAMILY">
              HF
            </span>
          </aside>
          <Sheet open={mobile} onOpenChange={setMobile}>
            <SheetContent
              side="left"
              className="navigation-sheet"
              aria-describedby={undefined}
            >
              <SheetHeader>
                <SheetTitle>HULK’S FAMILY</SheetTitle>
              </SheetHeader>
              <nav aria-label="Мобильная навигация">{navigation}</nav>
            </SheetContent>
          </Sheet>
          <main
            id="main"
            className={documentPage ? "document-page" : "workspace-page"}
            tabIndex={-1}
          >
            {checklist ? (
              <Checklists />
            ) : batches ? (
              <Batches />
            ) : (
              <Workspace
                id={id ? decodeURIComponent(id) : null}
                evaluationId={current.evaluation}
              />
            )}
          </main>
        </div>
        </BatchProvider>
      </WorkspaceProvider>
    </TooltipProvider>
  );
}
export function IconButton({
  label,
  children,
  onClick,
  pressed,
}: {
  label: string;
  children: React.ReactNode;
  onClick: () => void;
  pressed?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={label}
          aria-pressed={pressed}
          onClick={onClick}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
function Workspace({
  id,
  evaluationId,
}: {
  id: string | null;
  evaluationId: string | null;
}) {
  const workspace = useWorkspace();
  useEffect(() => {
    if (id) workspace.setActivePane("transcript");
  }, [id]);
  const storeLayout = (layout: Layout) => {
    if (workspace.narrow) return;
    try {
      localStorage.setItem("cqa.layout", JSON.stringify(layout));
    } catch {
      /* Optional layout preference. */
    }
  };
  const initialLayout = () => {
    try {
      const value = JSON.parse(localStorage.getItem("cqa.layout") ?? "null");
      if (
        value &&
        ["queue-panel", "transcript-panel", "quality-panel"].every(
          (key) =>
            typeof value[key] === "number" &&
            value[key] >= 0 &&
            value[key] <= 100,
        ) &&
        Math.abs(
          ["queue-panel", "transcript-panel", "quality-panel"].reduce(
            (sum, key) => sum + value[key],
            0,
          ) - 100,
        ) < 0.1
      )
        return value as Layout;
    } catch {
      /* Use the design proportions. */
    }
    return undefined;
  };
  const [layout] = useState(initialLayout);
  return (
    <section
      className="workspace"
      data-active-pane={workspace.activePane}
      data-narrow={workspace.narrow}
    >
      <div className="workspace-toolbar">
        <div className="workspace-location">
          <Inbox size={16} />
          <span>Диалоги</span>
          <span className="toolbar-separator">/</span>
          <span className="muted">Рабочая очередь</span>
        </div>
        <div className="pane-toggles">
          <IconButton
            label={
              workspace.narrow
                ? "Открыть очередь"
                : workspace.queueCollapsed
                  ? "Показать очередь"
                  : "Свернуть очередь"
            }
            pressed={workspace.queueCollapsed}
            onClick={workspace.toggleQueue}
          >
            <PanelLeftClose size={17} />
          </IconButton>
          <IconButton
            label={
              workspace.narrow
                ? workspace.activePane === "quality"
                  ? "Вернуться к диалогу"
                  : "Открыть качество"
                : workspace.qualityCollapsed
                  ? "Показать оценку"
                  : "Свернуть оценку"
            }
            pressed={workspace.qualityCollapsed}
            onClick={workspace.toggleQuality}
          >
            <PanelRightClose size={17} />
          </IconButton>
        </div>
      </div>
      <div
        className="mobile-pane-tabs"
        role="tablist"
        aria-label="Панели диалога"
      >
        {(["queue", "transcript", "quality"] as const).map((pane) => (
          <button
            key={pane}
            role="tab"
            data-workspace-tab={pane}
            aria-selected={workspace.activePane === pane}
            className={workspace.activePane === pane ? "active" : ""}
            onClick={() => workspace.setActivePane(pane)}
          >
            {pane === "queue" ? (
              <Inbox size={15} />
            ) : pane === "transcript" ? (
              <MessagesSquare size={15} />
            ) : (
              <ShieldCheck size={15} />
            )}{" "}
            {pane === "queue"
              ? "Очередь"
              : pane === "transcript"
                ? "Диалог"
                : "Качество"}
          </button>
        ))}
      </div>
      <ResizablePanelGroup
        orientation="horizontal"
        id="audit-workspace"
        className="workspace-panels"
        defaultLayout={layout}
        onLayoutChanged={storeLayout}
        disabled={workspace.narrow}
      >
        <ResizablePanel
          id="queue-panel"
          className="workspace-panel queue-panel"
          defaultSize="19%"
          minSize={workspace.narrow ? 0 : 210}
          maxSize="32%"
          collapsible
          collapsedSize="0%"
          panelRef={workspace.queueRef}
          inert={
            workspace.narrow
              ? workspace.activePane !== "queue"
              : workspace.queueCollapsed
          }
          aria-hidden={
            workspace.narrow
              ? workspace.activePane !== "queue"
              : workspace.queueCollapsed
          }
          onResize={workspace.onQueueResize}
        >
          <Conversations selectedId={id} />
        </ResizablePanel>
        <ResizableHandle
          aria-label="Изменить ширину очереди"
          className="workspace-handle"
        />
        {id ? (
          <ConversationView id={id} evaluationId={evaluationId} />
        ) : (
          <>
            <ResizablePanel
              id="transcript-panel"
              defaultSize="50.6%"
              minSize={workspace.narrow ? 0 : 320}
              className="workspace-panel transcript-panel"
              inert={workspace.narrow && workspace.activePane !== "transcript"}
              aria-hidden={
                workspace.narrow && workspace.activePane !== "transcript"
              }
            >
              <Empty
                title="Выберите диалог"
                text="Переписка, доказательства и оценка появятся здесь. Начните с очереди слева."
              />
            </ResizablePanel>
            <ResizableHandle
              aria-label="Изменить ширину оценки"
              className="workspace-handle"
            />
            <ResizablePanel
              id="quality-panel"
              defaultSize="30.4%"
              minSize={workspace.narrow ? 0 : 300}
              maxSize="43%"
              collapsible
              collapsedSize="0%"
              panelRef={workspace.qualityRef}
              inert={
                workspace.narrow
                  ? workspace.activePane !== "quality"
                  : workspace.qualityCollapsed
              }
              aria-hidden={
                workspace.narrow
                  ? workspace.activePane !== "quality"
                  : workspace.qualityCollapsed
              }
              onResize={workspace.onQualityResize}
              className="workspace-panel quality-panel"
            >
              <Empty
                title="Качество диалога"
                text="Оценки основаны на сохранённой версии чек-листа. Исходный результат и решения сохраняются отдельно."
              />
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>
    </section>
  );
}
