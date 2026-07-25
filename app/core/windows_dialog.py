from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

from app.core.process_utils import hidden_subprocess_flags


_DIALOG_SETUP = """
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$owner.Size = New-Object System.Drawing.Size(1, 1)
$owner.Show()
$owner.Activate()
"""


def _run_dialog_output(script: str, *, environment: dict[str, str] | None = None) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    env = os.environ.copy()
    if environment:
        env.update(environment)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
            env=env,
            creationflags=hidden_subprocess_flags(),
        )
    except FileNotFoundError as exc:
        raise RuntimeError("PowerShell could not be found, so the Windows file picker could not start.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The Windows file picker started but did not return within 300 seconds.") from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Windows file picker failed.{f' {details}' if details else ''}")
    return result.stdout.strip()


def _run_dialog(script: str, *, environment: dict[str, str] | None = None) -> Path | None:
    selected = _run_dialog_output(script, environment=environment)
    return Path(selected).resolve() if selected else None


def choose_video_file() -> Path | None:
    return _run_dialog(
        _DIALOG_SETUP
        + """
try {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = 'Choose video'
    $dialog.Filter = 'Video files|*.mp4;*.mov;*.mkv;*.avi;*.webm|All files|*.*'
    $dialog.RestoreDirectory = $true
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::Out.Write($dialog.FileName)
    }
} finally {
    $owner.Close()
    $owner.Dispose()
}
"""
    )


def choose_video_files() -> list[Path]:
    selected = _run_dialog_output(
        _DIALOG_SETUP
        + """
try {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = 'Choose source clips in recording order'
    $dialog.Filter = 'Video files|*.mp4;*.mov;*.mkv;*.avi;*.webm|All files|*.*'
    $dialog.Multiselect = $true
    $dialog.RestoreDirectory = $true
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::Out.Write(($dialog.FileNames -join [Environment]::NewLine))
    }
} finally {
    $owner.Close()
    $owner.Dispose()
}
"""
    )
    if not selected:
        return []
    return [Path(item).resolve() for item in selected.splitlines() if item.strip()]


def choose_project_file() -> Path | None:
    return _run_dialog(
        _DIALOG_SETUP
        + """
try {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = 'Open VCG project'
    $dialog.Filter = 'VCG video project|*.vcg-project.json|Legacy transcript project|*.vcg.json|JSON files|*.json|All files|*.*'
    $dialog.RestoreDirectory = $true
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::Out.Write($dialog.FileName)
    }
} finally {
    $owner.Close()
    $owner.Dispose()
}
"""
    )


def choose_visual_plan_file() -> Path | None:
    return _run_dialog(
        _DIALOG_SETUP
        + """
try {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = 'Open private visual plan'
    $dialog.Filter = 'VCG visual plan|visual-plan.json|JSON files|*.json|All files|*.*'
    $dialog.RestoreDirectory = $true
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::Out.Write($dialog.FileName)
    }
} finally {
    $owner.Close()
    $owner.Dispose()
}
"""
    )


def choose_visual_asset_file() -> Path | None:
    return _run_dialog(
        _DIALOG_SETUP
        + """
try {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = 'Import visual-production media'
    $dialog.Filter = 'Visual media|*.mp4;*.mov;*.mkv;*.avi;*.webm;*.png;*.jpg;*.jpeg;*.gif;*.webp|All files|*.*'
    $dialog.RestoreDirectory = $true
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::Out.Write($dialog.FileName)
    }
} finally {
    $owner.Close()
    $owner.Dispose()
}
"""
    )


def choose_project_save_file(default_name: str) -> Path | None:
    return _run_dialog(
        _DIALOG_SETUP
        + """
try {
    $dialog = New-Object System.Windows.Forms.SaveFileDialog
    $dialog.Title = 'Save VCG project'
    $dialog.FileName = $env:VCG_DIALOG_DEFAULT_NAME
    $dialog.DefaultExt = 'vcg.json'
    $dialog.Filter = 'VCG project|*.vcg.json|JSON files|*.json|All files|*.*'
    $dialog.RestoreDirectory = $true
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::Out.Write($dialog.FileName)
    }
} finally {
    $owner.Close()
    $owner.Dispose()
}
""",
        environment={"VCG_DIALOG_DEFAULT_NAME": default_name},
    )


def choose_output_folder() -> Path | None:
    return _run_dialog(
        """
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[Flags]
public enum FileOpenOptions : uint {
    FOS_NOCHANGEDIR = 0x00000008,
    FOS_PICKFOLDERS = 0x00000020,
    FOS_FORCEFILESYSTEM = 0x00000040,
    FOS_PATHMUSTEXIST = 0x00000800
}

[ComImport]
[Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
public class FileOpenDialogComObject { }

[ComImport]
[Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IShellItem {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetParent(out IShellItem ppsi);
    void GetDisplayName(uint sigdnName, out IntPtr ppszName);
    void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
    void Compare(IShellItem psi, uint hint, out int piOrder);
}

[ComImport]
[Guid("D57C7288-D4AD-4768-BE02-9D969532D960")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IFileOpenDialog {
    [PreserveSig] int Show(IntPtr parent);
    void SetFileTypes(uint count, IntPtr filterSpec);
    void SetFileTypeIndex(uint index);
    void GetFileTypeIndex(out uint index);
    void Advise(IntPtr events, out uint cookie);
    void Unadvise(uint cookie);
    void SetOptions(FileOpenOptions options);
    void GetOptions(out FileOpenOptions options);
    void SetDefaultFolder(IShellItem folder);
    void SetFolder(IShellItem folder);
    void GetFolder(out IShellItem folder);
    void GetCurrentSelection(out IShellItem item);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
    void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
    void GetResult(out IShellItem item);
    void AddPlace(IShellItem item, uint alignment);
    void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
    void Close(int errorCode);
    void SetClientGuid(ref Guid guid);
    void ClearClientData();
    void SetFilter(IntPtr filter);
    void GetResults(out IntPtr items);
    void GetSelectedItems(out IntPtr items);
}

public static class ModernFolderPicker {
    private const uint SIGDN_FILESYSPATH = 0x80058000;
    private const int ERROR_CANCELLED = unchecked((int)0x800704C7);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    public static string PickFolder() {
        IFileOpenDialog dialog = (IFileOpenDialog)new FileOpenDialogComObject();
        try {
            FileOpenOptions options;
            dialog.GetOptions(out options);
            dialog.SetOptions(
                options |
                FileOpenOptions.FOS_PICKFOLDERS |
                FileOpenOptions.FOS_FORCEFILESYSTEM |
                FileOpenOptions.FOS_PATHMUSTEXIST |
                FileOpenOptions.FOS_NOCHANGEDIR
            );
            dialog.SetTitle("Choose output folder");
            int result = dialog.Show(GetForegroundWindow());
            if (result == ERROR_CANCELLED) return null;
            Marshal.ThrowExceptionForHR(result);

            IShellItem item;
            dialog.GetResult(out item);
            try {
                IntPtr pathPointer;
                item.GetDisplayName(SIGDN_FILESYSPATH, out pathPointer);
                try {
                    return Marshal.PtrToStringUni(pathPointer);
                } finally {
                    Marshal.FreeCoTaskMem(pathPointer);
                }
            } finally {
                Marshal.ReleaseComObject(item);
            }
        } finally {
            Marshal.ReleaseComObject(dialog);
        }
    }
}
'@

$selected = [ModernFolderPicker]::PickFolder()
if ($selected) {
    [Console]::Out.Write($selected)
}
"""
    )
