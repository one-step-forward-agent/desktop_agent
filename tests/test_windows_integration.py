"""Opt-in UIA check using an owned synthetic WinForms process, not a user's applications."""
import os
from pathlib import Path
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt" or os.getenv("DEYLA_TEST_WINDOWS") != "1", reason="Opt-in synthetic native Windows test")


def test_native_windows_inspect_fill_invoke_read(tmp_path):
    from deyla_desktop.windows import Windows
    from pywinauto import Desktop
    import win32gui
    import win32process
    script = tmp_path / "synthetic-window.ps1"
    script.write_text("""Add-Type -AssemblyName System.Windows.Forms
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Deyla synthetic automation verification'
$form.Width = 440
$form.Height = 220
$form.ShowInTaskbar = $false
$form.StartPosition = 'CenterScreen'
$inputField = New-Object System.Windows.Forms.TextBox
$inputField.Name = 'SyntheticInput'
$inputField.SetBounds(20,20,320,30)
$button = New-Object System.Windows.Forms.Button
$button.Text = 'SyntheticSave'
$button.SetBounds(20,60,120,30)
$outputField = New-Object System.Windows.Forms.TextBox
$outputField.Name = 'SyntheticOutput'
$outputField.ReadOnly = $true
$outputField.SetBounds(20,105,320,30)
$button.Add_Click({ $outputField.Text = 'Saved: ' + $inputField.Text })
$form.Controls.AddRange(@($inputField,$button,$outputField))
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 45000
$timer.Add_Tick({ $form.Close() })
$timer.Start()
[System.Windows.Forms.Application]::Run($form)
""", encoding="utf-8-sig")
    # Hide the helper console; the small synthetic form is the UI under test.
    process = subprocess.Popen(["powershell.exe", "-NoProfile", "-STA", "-WindowStyle", "Hidden", "-File", str(script)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        desktop = Desktop(backend="uia")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            windows = []
            def found(handle, _):
                if win32gui.IsWindowVisible(handle) and win32process.GetWindowThreadProcessId(handle)[1] == process.pid:
                    windows.append(desktop.window(handle=handle).wrapper_object())
            win32gui.EnumWindows(found, None)
            if windows:
                break
            time.sleep(0.2)
        else:
            pytest.fail("Synthetic WinForms window did not become available")
        scoped = type("ScopedDesktop", (), {"windows": lambda self, **kwargs: windows})()
        # The test-only adapter enrolls just this owned helper PID as a supported app.
        controller = Windows(desktop=scoped, process_name=lambda pid: "notepad.exe" if pid == process.pid else "unsupported.exe")
        listed = controller.list()
        assert len(listed["windows"]) == 1
        state = controller.observe(listed["windows"][0]["id"])
        def find(state, label):
            return next(row["id"] for row in state["controls"] if row["label"] == label)
        state = controller.fill(find(state, "SyntheticInput"), "Deyla native test")
        state = controller.click(find(state, "SyntheticSave"))
        result = controller.read(find(state, "SyntheticOutput"))
        assert result["text"] == "Saved: Deyla native test"
        state = controller.observe()
        state = controller.fill(find(state, "SyntheticInput"), "")
        expected = "Literal +^%~(){} Тест"
        state = controller.type(find(state, "SyntheticInput"), expected)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            actual = controller.read(find(state, "SyntheticInput"))["text"]
            if actual == expected:
                break
            time.sleep(0.05)
        assert actual == expected
    finally:
        process.terminate()
        process.wait(timeout=10)
