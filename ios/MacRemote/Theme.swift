import SwiftUI

/// Central design tokens for the app. Dark-first, minimalist, with a soft
/// violet → cyan accent language. Everything visual references these so the
/// whole app reads as one system.
enum Theme {
    // MARK: Surfaces
    /// App background — near-black with a hint of blue.
    static let bg = Color(hex: 0x08080C)
    /// Slightly lifted background used behind scroll content.
    static let bgRaised = Color(hex: 0x0D0D14)
    /// Card / row surface.
    static let surface = Color(hex: 0x15151F)
    /// Elevated surface (pressed rows, sheets, fields).
    static let surfaceHi = Color(hex: 0x1D1D2A)

    // MARK: Text
    static let text = Color(hex: 0xF4F4F8)
    static let textDim = Color(hex: 0x9A9AAE)
    static let textFaint = Color(hex: 0x62627A)

    // MARK: Accent
    static let accent = Color(hex: 0x7C6CFF)      // soft violet
    static let accentDeep = Color(hex: 0x5B44E0)
    static let cyan = Color(hex: 0x35E0D8)         // secondary highlight
    static let green = Color(hex: 0x4ADE80)
    static let amber = Color(hex: 0xFBBF24)
    static let red = Color(hex: 0xF87171)

    // MARK: Lines
    static let hairline = Color.white.opacity(0.06)
    static let hairlineStrong = Color.white.opacity(0.10)

    // MARK: Gradients
    static let accentGradient = LinearGradient(
        colors: [accent, accentDeep],
        startPoint: .topLeading, endPoint: .bottomTrailing)

    static let glowGradient = LinearGradient(
        colors: [accent.opacity(0.9), cyan.opacity(0.7)],
        startPoint: .topLeading, endPoint: .bottomTrailing)

    // MARK: Metrics
    static let radius: CGFloat = 18
    static let radiusSmall: CGFloat = 12
}

extension Color {
    /// Build a color from a 0xRRGGBB literal.
    init(hex: UInt32, alpha: Double = 1) {
        let r = Double((hex >> 16) & 0xFF) / 255
        let g = Double((hex >> 8) & 0xFF) / 255
        let b = Double(hex & 0xFF) / 255
        self.init(.sRGB, red: r, green: g, blue: b, opacity: alpha)
    }
}
