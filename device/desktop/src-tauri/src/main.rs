use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::PathBuf,
    process::Command,
};

use tauri_plugin_shell::ShellExt;

fn desktop_log(message: &str) {
    let root = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
        .join("YouJustLead")
        .join("logs");
    if fs::create_dir_all(&root).is_ok() {
        if let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(root.join("desktop-agent.log"))
        {
            let _ = writeln!(file, "{message}");
        }
    }
}

fn release_sidecar_path() -> Result<PathBuf, String> {
    let executable = std::env::current_exe()
        .map_err(|error| format!("Unable to locate the desktop executable: {error}"))?;
    let directory = executable
        .parent()
        .ok_or("Unable to locate the desktop executable directory")?;
    Ok(directory.join("competition-agent-api.exe"))
}

fn launch_local_agent(app: &tauri::AppHandle) -> Result<(), String> {
    if cfg!(debug_assertions) {
        let source_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|path| path.parent())
            .ok_or("无法定位本地 Agent 源码目录")?;
        Command::new(std::env::var("YJL_PYTHON").unwrap_or_else(|_| "python".to_string()))
            .current_dir(source_root)
            .args(["main.py", "serve", "--host", "127.0.0.1", "--port", "8765"])
            .spawn()
            .map_err(|error| format!("无法启动本地 Agent：{error}"))?;
    } else {
        let sidecar_path = release_sidecar_path()?;
        if !sidecar_path.is_file() {
            return Err(format!(
                "Local Agent is missing: {}. Reinstall You Just Lead.",
                sidecar_path.display()
            ));
        }
        app.shell()
            .sidecar("competition-agent-api")
            .map_err(|error| format!("无法定位本地 Agent：{error}"))?
            .args(["serve", "--host", "127.0.0.1", "--port", "8765"])
            .spawn()
            .map_err(|error| format!("无法启动本地 Agent：{error}"))?;
    }
    desktop_log("Local Agent launch requested on 127.0.0.1:8765.");
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            if let Err(error) = launch_local_agent(app.handle()) {
                eprintln!("{error}");
                desktop_log(&format!("Local Agent launch failed: {error}"));
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running You Just Lead desktop application");
}
