// AI-PLC Registry ビューア（alpha）のメニューバーアプリ。
// メニューバーのアイコンから専用ウィンドウでビューアを開く。サーバ（server.py）はアプリが起動・停止する。
// ビルド: ./build.sh（リポジトリのパスと python3 のパスを Info.plist に埋め込む）
import AppKit
@preconcurrency import WebKit

let port = 8765
let baseURL = URL(string: "http://127.0.0.1:\(port)/")!

let logURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/AI-PLC Registry.log")

/// 診断ログ（~/Library/Logs/AI-PLC Registry.log）。コンソール.app でも読める
func diag(_ msg: String) {
    let line = "\(ISO8601DateFormatter().string(from: Date())) \(msg)\n"
    if let h = try? FileHandle(forWritingTo: logURL) { h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); try? h.close() }
    else { try? line.write(to: logURL, atomically: true, encoding: .utf8) }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate, NSWindowDelegate {
    private var statusItem: NSStatusItem!
    private var window: NSWindow?
    private var webView: WKWebView?
    private var server: Process?
    private var serverLog = ""
    private var statusLine: NSMenuItem!

    private var repo: String { Bundle.main.object(forInfoDictionaryKey: "AIPLCRepo") as? String ?? "" }
    private var python: String {
        let candidates = [Bundle.main.object(forInfoDictionaryKey: "AIPLCPython") as? String ?? "",
                          "/opt/homebrew/bin/python3", "/usr/bin/python3"]
        return candidates.first { !$0.isEmpty && FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/python3"
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "tablecells", accessibilityDescription: "AI-PLC Registry")
            button.toolTip = "AI-PLC Registry"
        }
        let menu = NSMenu()
        menu.addItem(withTitle: "Registry を開く", action: #selector(openWindow), keyEquivalent: "o")
        menu.addItem(withTitle: "再読み込み", action: #selector(reloadPage), keyEquivalent: "r")
        menu.addItem(withTitle: "ブラウザで開く", action: #selector(openInBrowser), keyEquivalent: "")
        menu.addItem(.separator())
        statusLine = NSMenuItem(title: "サーバ: 停止中", action: nil, keyEquivalent: "")
        statusLine.isEnabled = false
        menu.addItem(statusLine)
        menu.addItem(withTitle: "サーバを再起動", action: #selector(restartServer), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "終了（サーバも止める）", action: #selector(quit), keyEquivalent: "q")
        statusItem.menu = menu
        // 手で起動したとき（Spotlight・Finder・open）はウィンドウを開く。ログイン項目としての起動ではメニューバーだけ
        if launchedAsLoginItem() { ensureServer { _ in } } else { openWindow() }
    }

    // すでに起動中のアプリをもう一度開いたとき（Spotlight など）もウィンドウを出す
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openWindow()
        return false
    }

    private func launchedAsLoginItem() -> Bool {
        guard let ev = NSAppleEventManager.shared().currentAppleEvent else { return false }
        return ev.eventID == AEEventID(kAEOpenApplication) &&
            ev.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue == OSType(keyAELaunchedAsLogInItem)
    }

    func applicationWillTerminate(_ notification: Notification) { stopServer() }

    // MARK: server
    private func isServerUp(_ done: @escaping (Bool) -> Void) {
        var req = URLRequest(url: baseURL.appendingPathComponent("api/projects"), timeoutInterval: 3)
        req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200 &&
                (try? JSONSerialization.jsonObject(with: data ?? Data())) as? [String: Any] != nil
            DispatchQueue.main.async { done(ok) }
        }.resume()
    }

    private func ensureServer(_ done: @escaping (Bool) -> Void) {
        isServerUp { up in
            if up { self.setStatus(self.server == nil ? "サーバ: 起動中（他で起動したものを使用）" : "サーバ: 起動中"); done(true); return }
            self.startServer()
            self.waitForServer(tries: 40, done)
        }
    }

    private func startServer() {
        guard server?.isRunning != true else { return }
        let script = (repo as NSString).appendingPathComponent(".claude/db/registry_viewer/server.py")
        guard FileManager.default.fileExists(atPath: script) else {
            alert("server.py が見つかりません", script); return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [script, "--port", String(port), "--no-browser"]
        p.currentDirectoryURL = URL(fileURLWithPath: repo)
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] h in
            let s = String(data: h.availableData, encoding: .utf8) ?? ""
            DispatchQueue.main.async { self?.serverLog = String(((self?.serverLog ?? "") + s).suffix(4000)) }
        }
        p.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.server = nil; self?.setStatus("サーバ: 停止中") }
        }
        do { try p.run(); server = p; setStatus("サーバ: 起動しています…"); diag("server start pid=\(p.processIdentifier) python=\(python)") }
        catch { diag("server start failed: \(error)"); alert("サーバを起動できません", "\(python)\n\(error.localizedDescription)") }
    }

    private func waitForServer(tries: Int, _ done: @escaping (Bool) -> Void) {
        isServerUp { up in
            if up { self.setStatus("サーバ: 起動中"); done(true); return }
            if tries <= 0 || (self.server != nil && self.server?.isRunning == false) {
                diag("server not ready: \(self.serverLog.suffix(500))")
                self.setStatus("サーバ: 起動できませんでした")
                self.alert("サーバが起動しませんでした", self.serverLog.isEmpty ? "ポート \(port) が他で使われている可能性があります" : self.serverLog)
                done(false); return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { self.waitForServer(tries: tries - 1, done) }
        }
    }

    private func stopServer() {
        guard let p = server, p.isRunning else { return }
        diag("server stop pid=\(p.processIdentifier)")
        p.terminate()
        p.waitUntilExit()
        server = nil
    }

    private func setStatus(_ s: String) { statusLine?.title = s }

    // MARK: window
    @objc private func openWindow() {
        ensureServer { ok in
            guard ok else { return }
            if self.window == nil { self.makeWindow() } else { self.webView?.reload() }
            NSApp.activate(ignoringOtherApps: true)
            self.window?.makeKeyAndOrderFront(nil)
        }
    }

    private func makeWindow() {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()  // 絞り込み・画面共有モードの保存（localStorage）を残す
        let wv = WKWebView(frame: .zero, configuration: cfg)
        wv.uiDelegate = self
        wv.navigationDelegate = self
        wv.load(URLRequest(url: baseURL))
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        w.title = "AI-PLC Registry"
        w.contentView = wv
        w.isReleasedWhenClosed = false
        w.setFrameAutosaveName("AIPLCRegistryWindow")
        if !w.setFrameUsingName("AIPLCRegistryWindow") { w.center() }
        w.delegate = self
        window = w
        webView = wv
        addEditMenu()
    }

    // ⌘C / ⌘V / ⌘A を WKWebView で効かせるための Edit メニュー（メニューバーには出ない）
    private func addEditMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); appItem.submenu = NSMenu()
        appItem.submenu?.addItem(withTitle: "閉じる", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        let edit = NSMenuItem(); edit.submenu = NSMenu(title: "Edit")
        edit.submenu?.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.submenu?.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.submenu?.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.submenu?.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        edit.submenu?.addItem(withTitle: "Reload", action: #selector(reloadPage), keyEquivalent: "r")
        main.addItem(appItem); main.addItem(edit)
        NSApp.mainMenu = main
    }

    @objc private func reloadPage() { ensureServer { ok in if ok { self.webView?.reload() } } }
    @objc private func openInBrowser() { ensureServer { ok in if ok { NSWorkspace.shared.open(baseURL) } } }
    @objc private func restartServer() {
        if server == nil {
            isServerUp { up in
                if up { self.alert("他で起動したサーバを使っています", "そのサーバを止めてから再起動してください（このアプリが起動したサーバだけを再起動できます）") }
                else { self.ensureServer { ok in if ok { self.webView?.reload() } } }
            }
            return
        }
        stopServer()
        ensureServer { ok in if ok { self.webView?.reload() } }
    }
    @objc private func quit() { NSApp.terminate(nil) }

    private func alert(_ title: String, _ text: String) {
        let a = NSAlert(); a.messageText = title; a.informativeText = text
        NSApp.activate(ignoringOtherApps: true); a.runModal()
    }

    // MARK: WKNavigationDelegate（読み込みの成否を診断ログへ）
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            webView.evaluateJavaScript("[document.title, document.querySelectorAll('.row').length].join(' / ')") { r, e in
                diag("page loaded: \(r ?? "-") \(e.map { "err=\($0)" } ?? "")")
            }
        }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        diag("page load failed: \(error.localizedDescription)")
    }

    // MARK: WKUIDelegate（confirm / alert をネイティブで出す。<dialog> はページ側で動く）
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        alert(message, ""); completionHandler()
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = message
        a.addButton(withTitle: "OK"); a.addButton(withTitle: "キャンセル")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }
    // ページ内のリンクで別ウィンドウを開こうとしたら既定のブラウザへ
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = navigationAction.request.url { NSWorkspace.shared.open(u) }
        return nil
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
// SIGTERM / SIGINT（kill・ログアウト時など）でも applicationWillTerminate を通してサーバを止める
var signalSources: [DispatchSourceSignal] = []
for sig in [SIGTERM, SIGINT] {
    signal(sig, SIG_IGN)
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler { NSApp.terminate(nil) }
    src.resume()
    signalSources.append(src)
}
app.delegate = delegate
app.setActivationPolicy(.accessory)  // Dock に出さずメニューバーだけ
app.run()
