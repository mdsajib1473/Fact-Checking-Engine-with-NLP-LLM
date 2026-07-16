// Report renderer + interactions (Phase 4).
//
// Reads the pipeline JSON stored in sessionStorage by the home page and draws
// the claim-by-claim report: color-coded verdict badges, confidence bars,
// explanations, always-visible disclaimers (Rule 3), and expandable evidence
// panels with source links + relevance scores (Rule 10 — full transparency).
// The simple-view toggle hides explanation + evidence, leaving verdict,
// confidence, and disclaimer. All content is inserted via textContent — never
// innerHTML — so nothing retrieved from the web can inject markup.

(function () {
  "use strict";

  var root = document.getElementById("report-root");
  var simpleToggle = document.getElementById("simple-view-toggle");
  if (!root) return;

  var t = window.FC_I18N.t;

  // Verdict → badge + accent styling (Tailwind classes; scanned from this file
  // by the build). SUPPORTED green, DISPUTED yellow, FALSE red, UNVERIFIABLE gray.
  var VERDICT_STYLES = {
    SUPPORTED: {
      badge: "bg-green-100 text-green-800 dark:bg-green-900/60 dark:text-green-200",
      bar: "bg-green-500",
    },
    DISPUTED: {
      badge: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/60 dark:text-yellow-200",
      bar: "bg-yellow-500",
    },
    FALSE: {
      badge: "bg-red-100 text-red-800 dark:bg-red-900/60 dark:text-red-200",
      bar: "bg-red-500",
    },
    UNVERIFIABLE: {
      badge: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
      bar: "bg-slate-400",
    },
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function loadReport() {
    try {
      var raw = sessionStorage.getItem("factcheck_report");
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function renderEvidencePanel(evidence) {
    var details = el("details", "detail-section mt-3 rounded-lg border border-slate-200 dark:border-slate-700");
    var summary = el(
      "summary",
      "cursor-pointer select-none px-3 py-2 text-sm font-medium hover:bg-slate-50 dark:hover:bg-slate-800/60"
    );
    summary.textContent = t("report.evidence") + " (" + evidence.length + ")";
    details.appendChild(summary);

    var list = el("div", "space-y-3 border-t border-slate-200 p-3 dark:border-slate-700");
    if (!evidence.length) {
      list.appendChild(el("p", "text-sm text-slate-500 dark:text-slate-400", t("report.no_evidence")));
    }
    evidence.forEach(function (item) {
      var block = el("div", "rounded-md bg-slate-50 p-3 text-sm dark:bg-slate-800/60");

      var head = el("div", "flex flex-wrap items-center justify-between gap-2");
      var link = el("a", "font-medium text-blue-700 underline underline-offset-2 hover:text-blue-500 dark:text-blue-300");
      link.textContent = item.source_name || "source";
      link.href = item.source_url || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      head.appendChild(link);
      head.appendChild(
        el(
          "span",
          "text-xs text-slate-500 dark:text-slate-400",
          t("report.relevance") + ": " + Number(item.relevance_score || 0).toFixed(2)
        )
      );
      block.appendChild(head);

      block.appendChild(el("p", "mt-2 text-slate-700 dark:text-slate-300", item.evidence_snippet || ""));
      list.appendChild(block);
    });
    details.appendChild(list);
    return details;
  }

  function renderClaimCard(entry, index) {
    var verdict = entry.verdict || {};
    var label = String(verdict.label || "UNVERIFIABLE").toUpperCase();
    var style = VERDICT_STYLES[label] || VERDICT_STYLES.UNVERIFIABLE;
    var confidence = Math.max(0, Math.min(10, Number(verdict.confidence_score || 0)));

    var card = el(
      "article",
      "rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    );

    // Header: claim text + verdict badge.
    var head = el("div", "flex flex-wrap items-start justify-between gap-3");
    var claimWrap = el("div", "min-w-0 flex-1");
    claimWrap.appendChild(
      el("p", "text-xs font-medium uppercase tracking-wide text-slate-400 dark:text-slate-500", t("report.claim") + " " + (index + 1))
    );
    claimWrap.appendChild(el("p", "mt-1 font-medium leading-snug", entry.claim || ""));
    head.appendChild(claimWrap);
    head.appendChild(el("span", "shrink-0 rounded-full px-3 py-1 text-xs font-bold " + style.badge, label));
    card.appendChild(head);

    // Confidence: n/10 + bar.
    var confRow = el("div", "mt-3 flex items-center gap-3");
    confRow.appendChild(
      el("span", "text-xs text-slate-500 dark:text-slate-400", t("report.confidence") + ": " + confidence + "/10")
    );
    var barTrack = el("div", "h-1.5 w-32 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700");
    var barFill = el("div", "h-full rounded-full " + style.bar);
    barFill.style.width = confidence * 10 + "%";
    barTrack.appendChild(barFill);
    confRow.appendChild(barTrack);
    card.appendChild(confRow);

    // Explanation (hidden in simple view).
    if (verdict.explanation) {
      var explWrap = el("div", "detail-section mt-3");
      explWrap.appendChild(
        el("p", "text-xs font-medium uppercase tracking-wide text-slate-400 dark:text-slate-500", t("report.explanation"))
      );
      explWrap.appendChild(el("p", "mt-1 text-sm text-slate-700 dark:text-slate-300", verdict.explanation));
      card.appendChild(explWrap);
    }

    // Evidence panel (hidden in simple view).
    card.appendChild(renderEvidencePanel(entry.evidence || []));

    // Disclaimer — always visible, never collapsible (Rules 3/10).
    card.appendChild(
      el(
        "p",
        "mt-3 border-t border-slate-200 pt-3 text-xs italic text-slate-500 dark:border-slate-700 dark:text-slate-400",
        verdict.disclaimer || ""
      )
    );

    return card;
  }

  function render() {
    root.textContent = "";
    var report = loadReport();

    if (!report || !Array.isArray(report.claims)) {
      root.appendChild(el("p", "text-sm text-slate-500 dark:text-slate-400", t("report.missing")));
      return;
    }
    if (!report.claims.length) {
      root.appendChild(el("p", "text-sm text-slate-500 dark:text-slate-400", t("report.empty")));
      return;
    }

    report.claims.forEach(function (entry, i) {
      root.appendChild(renderClaimCard(entry, i));
    });
    applySimpleView();
  }

  function applySimpleView() {
    var simple = simpleToggle && simpleToggle.checked;
    root.querySelectorAll(".detail-section").forEach(function (node) {
      node.classList.toggle("hidden", !!simple);
    });
  }

  if (simpleToggle) simpleToggle.addEventListener("change", applySimpleView);

  // Re-render when the interface language switches so card labels translate.
  document.addEventListener("fc:lang", render);

  render();
})();
