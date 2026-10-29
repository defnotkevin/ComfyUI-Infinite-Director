import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";
app.registerExtension({
    name: "InfiniteDirector.CanvasAudit",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!["IDDirector", "IDTimeline", "IDStoreDesign", "IDStoreShotReference", "IDStoreTake"].includes(nodeData.name)) return;
        const previous = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function(message) {
            previous?.apply(this, arguments);
            if (!this._directorAudit) {
                const widget = ComfyWidgets.STRING(this, "Director audit", ["STRING", {multiline:true}], app).widget;
                widget.inputEl.readOnly = true;
                widget.serialize = false;
                this._directorAudit = widget;
            }
            this._directorAudit.value = (message.text || []).join("\n");
            this.setSize([Math.max(this.size[0], 440), Math.max(this.size[1], 360)]);
            this.setDirtyCanvas(true, true);
        };
    }
});
