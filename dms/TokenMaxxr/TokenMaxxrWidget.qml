import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import qs.Widgets
import qs.Modules.Plugins

// tokenmaxxr DankBar widget.
// Pill modes ("pill" setting):
//   soonest: "<tag> <countdown>" — each provider's longest window (30d, 7d…),
//            the one that resets soonest.
//   hottest: "<tag> <pct>%" — the most-used window across all providers.
//   cycle:   rotates "<tag> <pct>%" through providers (each one's hottest).
// Icon turns warning/error color when any window crosses warn/crit, and
// notify-send fires once per window per level crossed.
// Popout: every provider, every window, progress bar, reset time, $ amounts.
// Left click: popout. Right click: --refresh.
// Settings (edit ~/.config/DankMaterialShell/plugin_settings.json → "tokenMaxxr"):
//   "command":      shell command emitting schema:1 JSON  (default: tokenmaxxr --json)
//   "interval":     seconds between polls                  (default: 300)
//   "pill":         "soonest" | "hottest" | "cycle"       (default: soonest)
//   "cycleSeconds": seconds per provider in cycle mode     (default: 5)
//   "warn", "crit": percent thresholds                     (default: 70, 90)
//   "notify":       false disables notify-send             (default: true)
PluginComponent {
    id: root

    readonly property string command: pluginData?.command || "tokenmaxxr --json"
    readonly property int interval: pluginData?.interval || 300
    readonly property string pillMode: pluginData?.pill || "soonest"
    readonly property int cycleSeconds: pluginData?.cycleSeconds || 5
    readonly property int warn: pluginData?.warn || 70
    readonly property int crit: pluginData?.crit || 90
    readonly property bool notifyEnabled: pluginData?.notify ?? true
    property var doc: null
    property bool loading: false
    property string lastError: ""

    popoutWidth: 360

    readonly property var tags: ({
        "claude": "C", "kiro": "K", "ollama-cloud": "O", "clinepass": "CP", "opencode-go": "OG", "commandcode": "CC"
    })

    function tag(p) { return tags[p.id] || p.id.slice(0, 2).toUpperCase(); }

    function pctColor(pct) {
        return pct >= crit ? Theme.error : pct >= warn ? Theme.warning : Theme.primary;
    }

    function level(pct) { return pct >= crit ? 2 : pct >= warn ? 1 : 0; }

    // "$1.60 / $35" or "220.61 / 1000 credits"; "" when the window has no amounts.
    function amountText(w) {
        if (w.limit === undefined || w.limit === null) return "";
        const used = w.used || 0;
        if (w.unit === "$") return "$" + used.toFixed(2) + " / $" + w.limit;
        return used + " / " + w.limit + (w.unit ? " " + w.unit : "");
    }

    // Providers with usable data (ok, or stale from cache).
    readonly property var liveProviders: (doc?.providers || []).filter(p => p.status !== "no-auth" && p.status !== "error")

    // Most-used window of one provider (ties → soonest reset), or null.
    function hottestOf(p) {
        let best = null;
        for (const w of (p.windows || [])) {
            if (!best || w.pct_used > best.pct_used
                || (w.pct_used === best.pct_used && (w.reset_at || "~") < (best.reset_at || "~"))) best = w;
        }
        return best;
    }

    readonly property var hottest: {
        let best = null;
        for (const p of liveProviders) {
            const w = hottestOf(p);
            if (w && (!best || w.pct_used > best.window.pct_used)) best = { provider: p, window: w };
        }
        return best;
    }

    property int cycleIndex: 0
    Timer {
        interval: root.cycleSeconds * 1000
        running: root.pillMode === "cycle" && root.liveProviders.length > 1
        repeat: true
        onTriggered: root.cycleIndex++
    }

    function resetText(iso) {
        if (!iso) return "";
        const ms = new Date(iso).getTime() - Date.now();
        if (isNaN(ms)) return "";
        if (ms <= 0) return "resets now";
        const m = Math.floor(ms / 60000), h = Math.floor(m / 60), d = Math.floor(h / 24);
        if (d >= 1) return "resets in " + d + "d " + (h % 24) + "h";
        if (h >= 1) return "resets in " + h + "h " + (m % 60) + "m";
        return "resets in " + m + "m";
    }

    // Hours covered by a window label ("5h", "7d", "30d", "7d-opus" → 168). 0 = unknown.
    function windowHours(label) {
        const m = /^(\d+)(h|d)/.exec(label || "");
        return m ? parseInt(m[1]) * (m[2] === "d" ? 24 : 1) : 0;
    }

    // Per provider: its longest window. Across providers: the one resetting soonest.
    readonly property var soonest: {
        void tick;  // re-evaluate every minute so the countdown moves
        let best = null;
        for (const p of liveProviders) {
            let longest = null;
            for (const w of (p.windows || [])) {
                if (!w.reset_at) continue;
                if (!longest || windowHours(w.label) > windowHours(longest.label)) longest = w;
            }
            if (!longest) continue;
            const t = new Date(longest.reset_at).getTime();
            if (!isNaN(t) && (!best || t < best.t)) best = { t: t, provider: p, window: longest };
        }
        return best;
    }

    readonly property string pillText: {
        if (!doc) return loading ? "…" : "tokenmaxxr";
        if (pillMode === "hottest") {
            return hottest ? tag(hottest.provider) + " " + hottest.window.pct_used + "%" : "no-auth";
        }
        if (pillMode === "cycle") {
            const ps = liveProviders.filter(p => hottestOf(p));
            if (!ps.length) return "no-auth";
            const p = ps[cycleIndex % ps.length];
            return tag(p) + " " + hottestOf(p).pct_used + "%";
        }
        if (!soonest) return "no-auth";
        return tag(soonest.provider) + " " + resetText(soonest.window.reset_at).replace("resets in ", "").replace("resets now", "now");
    }

    readonly property color iconColor: lastError ? Theme.error
        : hottest && level(hottest.window.pct_used) > 0 ? pctColor(hottest.window.pct_used)
        : Theme.surfaceText

    // Highest level already notified per "provider/window"; drops back when
    // the window resets so the next crossing notifies again.
    property var notified: ({})

    // ponytail: one widget instance per bar/screen; only the first screen's
    // notifies. Two bars on the same screen would double-notify.
    readonly property bool notifier: !parentScreen || parentScreen === Quickshell.screens[0]

    onDocChanged: {
        if (!doc) return;
        const next = {};
        // Read doc directly: liveProviders may not have re-evaluated yet.
        for (const p of doc.providers || []) {
            if (p.status === "no-auth" || p.status === "error") continue;
            for (const w of (p.windows || [])) {
                const key = p.id + "/" + w.label, lvl = level(w.pct_used);
                next[key] = lvl;
                if (notifyEnabled && notifier && lvl > (notified[key] || 0)) {
                    const amt = amountText(w);
                    Quickshell.execDetached(["notify-send", "-a", "tokenmaxxr",
                        "-u", lvl === 2 ? "critical" : "normal",
                        p.name + " " + w.label + " at " + w.pct_used + "%",
                        (amt ? amt + ", " : "") + (resetText(w.reset_at) || "no reset time")]);
                }
            }
        }
        notified = next;
    }

    property int tick: 0
    Timer { interval: 60000; running: true; repeat: true; onTriggered: root.tick++ }

    function refresh(force) {
        if (fetcher.running) return;
        loading = true;
        // ponytail: prepend ~/.local/bin so `uv tool install` binaries resolve
        // even when the shell session's PATH doesn't reach quickshell.
        fetcher.command = ["sh", "-c",
            "PATH=\"$HOME/.local/bin:$PATH\" " + root.command + (force ? " --refresh" : "")];
        fetcher.running = true;
    }

    Component.onCompleted: refresh(false)

    Timer {
        interval: root.interval * 1000
        running: true
        repeat: true
        onTriggered: root.refresh(false)
    }

    Process {
        id: fetcher
        running: false
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    root.doc = JSON.parse(text);
                    root.lastError = "";
                } catch (e) {
                    root.lastError = "bad JSON from: " + root.command;
                }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: { if (text.trim()) root.lastError = text.trim().split("\n").pop(); }
        }
        onExited: (code, status) => {
            root.loading = false;
            if (code !== 0 && !root.lastError) root.lastError = "exit " + code;
        }
    }

    pillRightClickAction: function() { root.refresh(true); }

    horizontalBarPill: Component {
        Row {
            spacing: Theme.spacingXS
            DankIcon {
                name: "data_usage"
                size: root.iconSize
                color: root.iconColor
                anchors.verticalCenter: parent.verticalCenter
            }
            StyledText {
                text: root.pillText
                font.pixelSize: Theme.barTextSize(root.barThickness, root.barConfig?.fontScale, root.barConfig?.maximizeWidgetText)
                font.weight: Font.Medium
                color: Theme.surfaceText
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    verticalBarPill: Component {
        DankIcon {
            name: "data_usage"
            size: root.iconSize
            color: root.iconColor
        }
    }

    popoutContent: Component {
        PopoutComponent {
            headerText: "tokenmaxxr"
            detailsText: root.lastError ? root.lastError
                       : root.doc ? "fetched " + new Date(root.doc.fetched_at).toLocaleTimeString(Qt.locale(), Locale.ShortFormat)
                       : "loading…"
            showCloseButton: true
            headerActions: Component {
                DankActionButton {
                    iconName: "refresh"
                    onClicked: root.refresh(true)
                }
            }

            Column {
                width: parent.width
                spacing: Theme.spacingM
                leftPadding: Theme.spacingS
                rightPadding: Theme.spacingS
                bottomPadding: Theme.spacingS

                Repeater {
                    model: root.doc ? root.doc.providers : []
                    delegate: Column {
                        required property var modelData
                        width: parent.width - Theme.spacingS * 2
                        spacing: Theme.spacingXS

                        Row {
                            width: parent.width
                            StyledText {
                                text: modelData.name
                                font.pixelSize: Theme.fontSizeMedium
                                font.weight: Font.Medium
                                color: Theme.surfaceText
                                width: parent.width - statusText.width
                            }
                            StyledText {
                                id: statusText
                                text: modelData.status === "ok" ? "" : modelData.status
                                font.pixelSize: Theme.fontSizeSmall
                                color: modelData.status === "no-auth" ? Theme.surfaceVariantText : Theme.error
                            }
                        }

                        StyledText {
                            visible: modelData.status !== "ok" && !!modelData.error
                            width: parent.width
                            text: modelData.error || ""
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                            wrapMode: Text.WordWrap
                        }

                        Repeater {
                            model: modelData.windows || []
                            delegate: Column {
                                required property var modelData
                                width: parent.width
                                spacing: 2

                                Row {
                                    width: parent.width
                                    StyledText {
                                        text: modelData.label
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.surfaceVariantText
                                        width: 64
                                    }
                                    StyledText {
                                        text: root.resetText(modelData.reset_at)
                                        font.pixelSize: Theme.fontSizeSmall
                                        color: Theme.surfaceVariantText
                                        width: parent.width - 64 - pctLabel.width
                                        elide: Text.ElideRight
                                    }
                                    StyledText {
                                        id: pctLabel
                                        text: (root.amountText(modelData) ? root.amountText(modelData) + "  " : "") + modelData.pct_used + "%"
                                        font.pixelSize: Theme.fontSizeSmall
                                        font.weight: Font.Medium
                                        color: root.pctColor(modelData.pct_used)
                                    }
                                }

                                Rectangle {
                                    width: parent.width
                                    height: 6
                                    radius: 3
                                    color: Theme.surfaceVariantAlpha
                                    Rectangle {
                                        width: parent.width * Math.min(100, modelData.pct_used) / 100
                                        height: parent.height
                                        radius: parent.radius
                                        color: root.pctColor(modelData.pct_used)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
