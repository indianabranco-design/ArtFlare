import SwiftUI
import WebKit
struct WebView: UIViewRepresentable {
    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        let web = WKWebView(frame: .zero, configuration: cfg)
        return web
    }
    func updateUIView(_ uiView: WKWebView, context: Context) {
        uiView.load(URLRequest(url: AppConstants.appURL))
    }
}
