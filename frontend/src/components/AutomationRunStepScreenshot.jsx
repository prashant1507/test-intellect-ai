import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  FloatingTooltip,
  InlineDownloadIconButton,
  downloadUrlAsFile,
  suggestedFilenameFromUrl,
} from "./common";

function resolveStepScreenshotUrl(runId, step) {
  if (!step || typeof step !== "object") return null;
  if (step.screenshot_url) return step.screenshot_url;
  const p = step.screenshot_path;
  if (runId == null || p == null || p === "") return null;
  const parts = String(p).split("/").filter(Boolean);
  const tail = parts.pop();
  if (!tail) return null;
  return `/api/automation/artifacts/${encodeURIComponent(String(runId))}/${encodeURIComponent(tail)}`;
}

function stepIsSkippedAfterPriorFailure(step) {
  return /skipped\s*\(\s*previous\s+step\s+failed\s*\)/i.test(String(step?.err || ""));
}

const SHOT_PAD = 20;

function shouldOpenShotDetailsByDefault(step) {
  if (!step) return false;
  if (String(step.err || "").trim()) return true;
  if (step.pass === false || step.pass === 0) return true;
  return false;
}

export function stepShotAccordionId(runId, step, indexFallback) {
  const r = String(runId ?? "none");
  if (step && step.step_index !== undefined && step.step_index !== null) {
    return `${r}-si${String(step.step_index)}`;
  }
  return `${r}-i${String(indexFallback)}`;
}

export function getFirstFailingStepShotAccordionId(runId, steps) {
  if (runId == null || !Array.isArray(steps) || steps.length === 0) return null;
  const sorted = [...steps].sort(
    (a, b) => Number(a?.step_index ?? 0) - Number(b?.step_index ?? 0),
  );
  for (const s of sorted) {
    if (!shouldOpenShotDetailsByDefault(s)) continue;
    if (!resolveStepScreenshotUrl(runId, s)) continue;
    return stepShotAccordionId(runId, s, 0);
  }
  return null;
}

export function AutomationRunStepScreenshot({
  runId,
  step,
  defaultExpanded = true,
  accordionId,
  expandedAccordionId = null,
  onExpandedAccordionChange,
}) {
  const [loadFailed, setLoadFailed] = useState(false);
  const [natural, setNatural] = useState(null);
  const imgRef = useRef(null);
  const url = resolveStepScreenshotUrl(runId, step);
  const accordionMode =
    accordionId != null && String(accordionId).length > 0 && typeof onExpandedAccordionChange === "function";

  const openByDefault = useMemo(
    () =>
      defaultExpanded === false
        ? false
        : Boolean(url && shouldOpenShotDetailsByDefault(step)),
    [url, defaultExpanded, step?.err, step?.pass, step?.step_index],
  );
  const [localOpen, setLocalOpen] = useState(() => (accordionMode ? false : openByDefault));

  useEffect(() => {
    setLoadFailed(false);
    setNatural(null);
    if (accordionMode) return;
    setLocalOpen(openByDefault);
  }, [url, openByDefault, accordionMode]);

  const isOpen = accordionMode
    ? expandedAccordionId != null && expandedAccordionId === accordionId
    : localOpen;

  const applyNaturalFromImg = (el) => {
    if (!el) return;
    if (el.naturalWidth > 0 && el.naturalHeight > 0) {
      setNatural((prev) => {
        const n = { w: el.naturalWidth, h: el.naturalHeight };
        if (prev && prev.w === n.w && prev.h === n.h) return prev;
        return n;
      });
    }
  };

  useLayoutEffect(() => {
    if (!isOpen) return;
    const el = imgRef.current;
    if (el?.complete) applyNaturalFromImg(el);
  }, [isOpen, url]);

  const screenshotDownloadName = useMemo(
    () =>
      suggestedFilenameFromUrl(
        url,
        step?.step_index != null ? `screenshot-step-${step.step_index}.png` : "screenshot.png",
      ),
    [url, step?.step_index],
  );

  if (loadFailed) {
    return (
      <p className="automation-spike-step-shot-missing" role="note">
        Screenshot file is not available (removed by retention or missing on disk).
      </p>
    );
  }
  if (!url) {
    if (stepIsSkippedAfterPriorFailure(step)) {
      return (
        <p className="automation-spike-step-shot-missing" role="note">
          Skipped (previous step failed)
        </p>
      );
    }
    return null;
  }

  const onToggle = (e) => {
    const open = e.currentTarget.open;
    if (accordionMode) {
      if (open) onExpandedAccordionChange(accordionId);
      else if (expandedAccordionId === accordionId) onExpandedAccordionChange(null);
    } else {
      setLocalOpen(open);
    }
  };

  const onImgLoad = (e) => {
    applyNaturalFromImg(e.currentTarget);
  };

  const bodyStyle =
    isOpen && natural
      ? {
          width: "100%",
          maxWidth: `min(100%, ${natural.w + SHOT_PAD}px)`,
          maxHeight: `min(95dvh, ${natural.h + SHOT_PAD}px)`,
        }
      : undefined;

  const onDownloadShot = (e) => {
    e.preventDefault();
    e.stopPropagation();
    void downloadUrlAsFile(url, screenshotDownloadName);
  };

  return (
    <details
      className="automation-spike-step-shot"
      open={isOpen}
      onToggle={onToggle}
    >
      <summary className="automation-spike-step-shot-summary automation-spike-step-shot-summary--row">
        <span className="automation-spike-step-shot-summary-text">Screenshot</span>
        <span
          className="automation-spike-step-shot-dl-wrap"
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          role="presentation"
        >
          <FloatingTooltip text="Download screenshot">
            <InlineDownloadIconButton
              className="automation-spike-step-shot-dl"
              ariaLabel="Download screenshot"
              onClick={onDownloadShot}
            />
          </FloatingTooltip>
        </span>
      </summary>
      <div
        className={`automation-spike-step-shot-body${bodyStyle ? " automation-spike-step-shot-body--fit" : ""}`}
        style={bodyStyle}
      >
        <img
          key={url}
          ref={imgRef}
          src={url}
          alt=""
          className="automation-spike-step-shot-img"
          loading="lazy"
          onLoad={onImgLoad}
          onError={() => setLoadFailed(true)}
        />
      </div>
    </details>
  );
}
