"""
PCM Channel Config Generator - IRIG 106 Ch.4 Compliant
Standalone desktop application using pywebview.
"""
import json
import os
import sys
import webview

from pcm_engine import allocate_channels, validate_config, auto_calculate_frame_size
from export_excel import export_to_excel


def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


class Api:
    """Python API exposed to JavaScript via pywebview."""

    def __init__(self, window=None):
        self._window = window

    def set_window(self, window):
        self._window = window

    # ── File I/O ──

    def open_config(self):
        """Open file dialog and load JSON config."""
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=("JSON Files (*.json)",),
        )
        if not result or not result[0]:
            return {"success": False, "reason": "cancelled"}

        filepath = result[0]
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                config = json.load(f)
            return {"success": True, "config": config, "path": filepath}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    def save_config(self, config_json: str):
        """Save config to JSON file."""
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="pcm_config.json",
            file_types=("JSON Files (*.json)",),
        )
        if not result:
            return {"success": False, "reason": "cancelled"}

        filepath = result if isinstance(result, str) else result[0] if result else None
        if not filepath:
            return {"success": False, "reason": "cancelled"}

        if not filepath.endswith(".json"):
            filepath += ".json"

        try:
            config = json.loads(config_json)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            return {"success": True, "path": filepath}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # ── Channel Table Generation ──

    def generate(self, config_json: str):
        """Generate optimal PCM channel table."""
        try:
            config = json.loads(config_json)
            result = allocate_channels(config)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def validate(self, config_json: str):
        """Validate config against IRIG-106."""
        try:
            config = json.loads(config_json)
            msgs = validate_config(config)
            return json.dumps(msgs, ensure_ascii=False)
        except Exception as e:
            return json.dumps([{"type": "error", "msg": str(e)}])

    def auto_size(self, config_json: str):
        """Auto-calculate optimal frame size."""
        try:
            config = json.loads(config_json)
            result = auto_calculate_frame_size(config)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Excel Export ──

    def export_excel(self, config_json: str, result_json: str):
        """Export channel table to Excel."""
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="pcm_channel_table.xlsx",
            file_types=("Excel Files (*.xlsx)",),
        )
        if not result:
            return {"success": False, "reason": "cancelled"}

        filepath = result if isinstance(result, str) else result[0] if result else None
        if not filepath:
            return {"success": False, "reason": "cancelled"}

        if not filepath.endswith(".xlsx"):
            filepath += ".xlsx"

        try:
            config = json.loads(config_json)
            res = json.loads(result_json)
            export_to_excel(config, res, filepath)
            return {"success": True, "path": filepath}
        except Exception as e:
            return {"success": False, "reason": str(e)}


def main():
    api = Api()

    html_path = resource_path(os.path.join("ui", "index.html"))

    window = webview.create_window(
        title="PCM Channel Config Generator | IRIG 106 Ch.4",
        url=html_path,
        js_api=api,
        width=1400,
        height=900,
        min_size=(1024, 700),
        text_select=True,
    )
    api.set_window(window)

    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
