// Pocket XR's Quick Access panel: the Gaming Mode controls for Pocket XR for Steam Deck.
// It talks to Pocket XR's Gaming Mode service through this plugin's backend (main.py). GPL-3.0, as Pocket XR.
import { ButtonItem, PanelSection, PanelSectionRow, SliderField, staticClasses } from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaGlasses } from "react-icons/fa";

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
};

const request = callable<[req: Record<string, unknown>], Status>("request");

const MODES: { key: string; title: string; line: string }[] = [
  { key: "space", title: "Screen in space", line: "Stays put as you turn your head." },
  { key: "steady", title: "Steady", line: "The glasses hold the screen as you move around." },
  { key: "off", title: "Off", line: "The picture as it is, moving with your head." },
];

function statusLine(st: Status | null): string {
  if (st === null) return "Looking for Pocket XR...";
  if (!st.running) return "Pocket XR isn't running. Install or update it from Desktop Mode.";
  if (!st.glasses) return "Plug your glasses into the Deck's USB-C port.";
  if (!st.tracking) return `${st.glasses}: no head tracking on these glasses, so the picture is shown as it is.`;
  return `${st.glasses} · head tracking on`;
}

function Content() {
  const [st, setSt] = useState<Status | null>(null);
  const [size, setSize] = useState<number | null>(null);

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
  const modes = MODES.filter((m) => m.key !== "steady" || st?.steady_ok);
  const shownSize = size ?? Math.round((st?.size ?? 0.8) * 100);

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <div style={{ fontSize: "13px", lineHeight: "18px", color: "#b8bcbf" }}>{statusLine(st)}</div>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="View">
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
      <PanelSection title="Screen">
        <PanelSectionRow>
          <SliderField
            label="Size"
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
            Recentre
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", lineHeight: "16px", color: "#8b929a" }}>
            Without this menu: hold L4 to recentre, hold R4 to switch view.
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
