// Pocket XR's Quick Access panel: the Gaming Mode controls for Pocket XR for Steam Deck.
// It talks to Pocket XR's Gaming Mode service through this plugin's backend (main.py). GPL-3.0, as Pocket XR.
import { ButtonItem, PanelSection, PanelSectionRow, SliderField, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
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
  curve?: number;
  readability?: boolean;
  calibrating?: boolean;
  calibrate_label?: string; // in the panel's language, from the service
  calibrate_line?: string;
  calibration_text?: string;
  calibrate_start_text?: string; // a toast when a calibration starts
  keys_line?: string; // how another controller does the back buttons' jobs (Steam Input keys)
  sticks?: boolean; // the Deck's stick clicks do Pocket XR's jobs (hold L3, hold R3, L3 three times)
  taps?: boolean; // taps on the glasses: two recentre, three switch view
  tap_sensitivity?: number; // percent
  tap_sensitivity_range?: number[];
  tap_sensitivity_label?: string;
  tap_sensitivity_line?: string;
  recentre_roll?: boolean; // Recentre includes head tilt
  recentre_roll_label?: string;
  recentre_roll_line?: string;
  glasses_buttons?: boolean | null; // let go of the glasses so their own buttons work; null: not offered
  brightness?: number | null; // the glasses' brightness, 0 to brightness_max, while Pocket XR has them; null: hidden
  brightness_max?: number;
  brightness_label?: string;
  brightness_line?: string;
  glasses_buttons_label?: string;
  glasses_buttons_line?: string;
  taps_label?: string;
  taps_line?: string;
  sticks_label?: string;
  sticks_line?: string;
  readability_label?: string; // in the panel's language, from the service
  readability_line?: string;
  lang?: string;
  logs?: string;
  logs_error?: string;
  notice?: string; // already in the panel's language: e.g. XR Gaming's driver is running
  version?: string; // the Gaming Mode service's Pocket XR version (from 0.7.6; none before)
  panel?: string; // this panel's version, added by its backend (main.py)
  actions?: { op: string; label: string }[]; // fixes the service offers, labels already in the panel's language
  action_result?: string;
};

const request = callable<[req: Record<string, unknown>], Status>("request");

function toast(body: string, duration = 5000) {
  toaster.toast({ title: "Pocket XR", body, duration });
}

// A calibration's result as a toast, even with Quick Access closed (the glasses are off and lying still by then)
let watching = false;
async function watchCalibration() {
  if (watching) return;
  watching = true;
  try {
    const end = Date.now() + 30000;
    while (Date.now() < end) {
      await new Promise((r) => setTimeout(r, 500));
      const s = await request({ op: "status" });
      if (!s.running) break;
      if (!s.calibrating) {
        if (s.calibration_text) toast(s.calibration_text, 6000);
        break;
      }
    }
  } finally {
    watching = false;
  }
}

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
  const [curve, setCurve] = useState<number | null>(null);
  const [logs, setLogs] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

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
  const shownCurve = curve ?? Math.round((st?.curve ?? 0) * 100);
  const calibrate = async () => {
    const r = await request({ op: "calibrate" });
    setSt(r);
    if (r.calibrating) {
      toast(r.calibrate_start_text || "Calibrating: take the glasses off and lay them on something still for 4 seconds.");
      watchCalibration();
    } else if (r.calibration_text) {
      toast(r.calibration_text);
    }
  };
  const act = async (op: string) => {
    setDone(null);
    const r = await request({ op });
    setSt(r);
    setDone(r.action_result || r.why || null);
  };

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <div style={{ fontSize: "13px", lineHeight: "18px", color: "#b8bcbf" }}>{statusLine(st, w)}</div>
          {st?.notice ? (
            <div style={{ fontSize: "13px", lineHeight: "18px", color: "#ffc857", marginTop: "6px" }}>{st.notice}</div>
          ) : null}
          {st?.running && st.panel && st.version !== st.panel ? (
            <div style={{ fontSize: "13px", lineHeight: "18px", color: "#ffc857", marginTop: "6px" }}>
              {w.versionMismatch.replace("{service}", st.version || "≤ 0.7.5").replace("{panel}", st.panel)}
            </div>
          ) : null}
        </PanelSectionRow>
        {(st?.actions || []).map((a) => (
          <PanelSectionRow key={a.op}>
            <ButtonItem layout="below" onClick={() => act(a.op)}>
              {a.label}
            </ButtonItem>
          </PanelSectionRow>
        ))}
        {done ? (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", lineHeight: "16px", color: "#b8bcbf" }}>{done}</div>
          </PanelSectionRow>
        ) : null}
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
          <SliderField
            label={w.curve}
            value={shownCurve}
            min={0}
            max={100}
            step={10}
            showValue
            valueSuffix="%"
            disabled={!ready || st?.mode !== "space"}
            onChange={(v: number) => {
              setCurve(v);
              send({ op: "set_curve", curve: v / 100 });
            }}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label={st?.readability_label || "Readability"}
            description={st?.readability_line}
            checked={!!st?.readability}
            disabled={!st?.running}
            onChange={(on: boolean) => {
              setSize(null); // the size follows the service's: readability changes it, and off puts it back
              send({ op: "set_readability", on });
            }}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={!ready} onClick={() => send({ op: "recentre" })}>
            {w.recentre}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!ready || !st?.tracking || !!st?.calibrating}
            description={st?.calibrating ? "..." : st?.calibration_text || st?.calibrate_line}
            onClick={calibrate}
          >
            {st?.calibrate_label || "Calibrate (hold still)"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", lineHeight: "16px", color: "#8b929a" }}>
            {w.buttons}
          </div>
          {st?.keys_line ? (
            <div style={{ fontSize: "12px", lineHeight: "16px", color: "#8b929a", marginTop: "6px" }}>{st.keys_line}</div>
          ) : null}
        </PanelSectionRow>
        {st?.brightness_label && st.brightness !== null && st.brightness !== undefined ? (
          <PanelSectionRow>
            <SliderField
              label={st.brightness_label}
              description={st.brightness_line}
              value={st.brightness}
              min={0}
              max={st.brightness_max || 7}
              step={1}
              showValue
              disabled={!ready}
              onChange={(v: number) => send({ op: "set_brightness", level: v })}
            />
          </PanelSectionRow>
        ) : null}
        {st?.glasses_buttons_label && st.glasses_buttons !== null && st.glasses_buttons !== undefined ? (
          <PanelSectionRow>
            <ToggleField
              label={st.glasses_buttons_label}
              description={st.glasses_buttons_line}
              checked={!!st.glasses_buttons}
              disabled={!ready}
              onChange={(on: boolean) => send({ op: "glasses_buttons", on })}
            />
          </PanelSectionRow>
        ) : null}
        {st?.taps_label ? (
          <PanelSectionRow>
            <ToggleField
              label={st.taps_label}
              description={st.taps_line}
              checked={!!st.taps}
              disabled={!st.running}
              onChange={(on: boolean) => send({ op: "set_taps", on })}
            />
          </PanelSectionRow>
        ) : null}
        {st?.taps && st.tap_sensitivity_label ? (
          <PanelSectionRow>
            <SliderField
              label={st.tap_sensitivity_label}
              description={st.tap_sensitivity_line}
              value={st.tap_sensitivity ?? 100}
              min={(st.tap_sensitivity_range || [25, 300])[0]}
              max={(st.tap_sensitivity_range || [25, 300])[1]}
              step={25}
              showValue
              valueSuffix="%"
              disabled={!st.running}
              onChange={(v: number) => send({ op: "set_tap_sensitivity", percent: v })}
            />
          </PanelSectionRow>
        ) : null}
        {st?.recentre_roll_label ? (
          <PanelSectionRow>
            <ToggleField
              label={st.recentre_roll_label}
              description={st.recentre_roll_line}
              checked={!!st.recentre_roll}
              disabled={!st.running}
              onChange={(on: boolean) => send({ op: "set_recentre_roll", on })}
            />
          </PanelSectionRow>
        ) : null}
        {st?.sticks_label ? (
          <PanelSectionRow>
            <ToggleField
              label={st.sticks_label}
              description={st.sticks_line}
              checked={!!st.sticks}
              disabled={!st.running}
              onChange={(on: boolean) => send({ op: "set_sticks", on })}
            />
          </PanelSectionRow>
        ) : null}
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
