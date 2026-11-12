// Pocket XR's Quick Access panel: the Gaming Mode controls for Pocket XR for Steam Deck.
// It talks to Pocket XR's Gaming Mode service through this plugin's backend (main.py). GPL-3.0, as Pocket XR.
import { ButtonItem, PanelSection, PanelSectionRow, SliderField, staticClasses } from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaGlasses } from "react-icons/fa";
import { fill, Words, wordsFor } from "./words";

type Status = {
  running: boolean;
  why?: string;
  gaming?: boolean;
  glasses?: string | null;
  tracking?: boolean;
  steady_ok?: boolean;
  mode?: string;
  chosen?: string;
  size?: number;
  lang?: string;
  logs?: string;
  logs_error?: string;
};

const request = callable<[req: Record<string, unknown>], Status>("request");

function statusLine(st: Status | null, w: Words): string {
  if (st === null) return w.looking;
  if (!st.running) return w.notRunning;
  if (!st.glasses) return w.plugIn;
  if (!st.tracking) return fill(w.noTracking, { glasses: st.glasses });
  return fill(w.trackingOn, { glasses: st.glasses });
}

function Content() {
  const [st, setSt] = useState<Status | null>(null);
  const [size, setSize] = useState<number | null>(null);
  const [logs, setLogs] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const poll = async () => {
      const s = await request({ op: "status" });
      if (live) setSt(s);
    };
    poll();
    const t = setInterval(poll, 1000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, []);

  const send = async (req: Record<string, unknown>) => setSt(await request(req));
  const ready = !!(st && st.running && st.glasses);
  const w = wordsFor(st?.lang);
  const modes = [
    { key: "space", title: w.spaceTitle, line: w.spaceLine },
    { key: "steady", title: w.steadyTitle, line: w.steadyLine },
    { key: "off", title: w.offTitle, line: w.offLine },
  ].filter((m) => m.key !== "steady" || st?.steady_ok);
  const sendLogs = async () => {
    setLogs(w.logsReady);
    const r = await request({ op: "send_logs" });
    if (r.logs) setLogs(fill(w.logsSaved, { name: r.logs }));
    else setLogs(fill(w.logsFailed, { error: r.logs_error || r.why || "?" }));
  };
  const shownSize = size ?? Math.round((st?.size ?? 0.8) * 100);

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <div style={{ fontSize: "13px", lineHeight: "18px", color: "#b8bcbf" }}>{statusLine(st, w)}</div>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title={w.view}>
        {modes.map((m) => (
          <PanelSectionRow key={m.key}>
            <ButtonItem
              layout="below"
              disabled={!ready}
              description={m.line}
              onClick={() => send({ op: "set_mode", mode: m.key })}
            >
              {(st?.chosen === m.key ? "● " : "") + m.title}
            </ButtonItem>
          </PanelSectionRow>
        ))}
      </PanelSection>
      <PanelSection title={w.screen}>
        <PanelSectionRow>
          <SliderField
            label={w.size}
            value={shownSize}
            min={30}
            max={120}
            step={5}
            showValue
            valueSuffix="%"
            disabled={!ready || st?.mode !== "space"}
            onChange={(v: number) => {
              setSize(v);
              send({ op: "set_size", size: v / 100 });
            }}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!ready} onClick={() => send({ op: "recentre" })}>
            {w.recentre}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", lineHeight: "16px", color: "#8b929a" }}>
            {w.buttons}
          </div>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!st?.running} onClick={sendLogs}>
            {w.sendLogs}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", lineHeight: "16px", color: logs ? "#b8bcbf" : "#8b929a" }}>
            {logs ?? w.logsLine}
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "Pocket XR",
  titleView: <div className={staticClasses.Title}>Pocket XR</div>,
  content: <Content />,
  icon: <FaGlasses />,
  onDismount() {},
}));
