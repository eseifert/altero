// Drive the actual modal controls. Never replace prompt or reconciliation code.
function watchAcceptanceDialogs(rules) {
  const remaining = [...rules];
  const trace = [];
  const errors = [];
  const watcher = {
    observe(window, topic) {
      if (topic !== "domwindowopened") return;
      window.addEventListener("load", () => window.setTimeout(() => {
        const uri = window.location.href;
        if (uri !== "chrome://zotero/content/merge.xhtml" && !uri.includes("commonDialog.xhtml")
            && !uri.includes("hardConfirmationDialog.xhtml")) return;
        const rule = remaining.shift();
        try {
          if (!rule) throw new Error(`Unexpected dialog ${uri}`);
          if (rule.kind === "merge") {
            if (uri !== "chrome://zotero/content/merge.xhtml") throw new Error("Expected merge dialog");
            const io = window.arguments[0].wrappedJSObject ?? window.arguments[0];
            const conflicts = io.dataIn.conflicts;
            if (conflicts.length !== 1 || (conflicts[0].left.key ?? conflicts[0].right.key) !== rule.key) {
              throw new Error("Merge dialog does not contain the expected object");
            }
            const group = window.document.querySelector("merge-group");
            const pane = rule.side === "local" ? group.leftPane : group.rightPane;
            pane.groupbox.dispatchEvent(new window.MouseEvent("click", {bubbles: true}));
            if (pane.getAttribute("selected") !== "true") throw new Error("Merge pane was not selected");
            trace.push({kind: "merge", key: rule.key, side: rule.side,
              type: io.dataIn.type ?? group.type});
            window.document.getElementById("merge-window").getButton("finish").click();
          } else if (rule.kind === "prompt") {
            const text = window.document.getElementById("infoBody").textContent;
            if (!text.includes(rule.text)) throw new Error(`Wrong prompt: ${text}`);
            const dialog = window.document.querySelector("dialog");
            const button = ["accept", "cancel", "extra1", "extra2"].map(name => dialog.getButton(name))
              .find(button => button && !button.hidden && button.label === rule.button);
            if (!button) throw new Error(`Missing prompt button ${rule.button}`);
            const started = Date.now();
            const timer = window.setInterval(() => {
              if (button.disabled && Date.now() - started < 10000) return;
              window.clearInterval(timer);
              if (button.disabled) {
                errors.push("Prompt button remained disabled");
                window.close();
                return;
              }
              trace.push({kind: "prompt", text, button: rule.button});
              button.click();
            }, 100);
          } else throw new Error(`Unknown dialog rule ${rule.kind}`);
        } catch (error) {
          errors.push(error.message);
          window.close();
        }
      }, 0), {once: true});
    }
  };
  Services.ww.registerNotification(watcher);
  return {
    trace,
    finish() {
      Services.ww.unregisterNotification(watcher);
      if (errors.length) throw new Error(errors.join("; "));
      if (remaining.length) throw new Error("Expected acceptance dialog never appeared");
    }
  };
}
