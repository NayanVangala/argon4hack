import SwiftUI

// Scene · Butter palette (lime / yellow / white / true-black, red only for recording + wipe)
extension Color {
    init(hex: UInt32) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: 1)
    }
}

enum Theme {
    static let paper = Color(hex: 0xFAFAFA)      // app background
    static let ink = Color(hex: 0x1E1E1E)        // text, primary buttons
    static let trueBlack = Color(hex: 0x0F0F0F)  // timeline strip, Live
    static let pill = Color(hex: 0xEDEDED)       // nav pill, chips, inputs
    static let secondary = Color(hex: 0x6B6B6B)  // secondary text
    static let accent = Color(hex: 0xBCF015)     // lime, primary accent (focus, highlight)
    static let yellow = Color(hex: 0xE9D352)     // Butter yellow, secondary accent
    static let tint = Color(hex: 0xE9D352)       // yellow (verified chips, quote blocks)
    static let soft = Color(hex: 0xBCF015)       // lime (action blocks)
    static let greyBlue = Color(hex: 0xE2E2E2)   // quiet blocks (Butter hairline grey)
    static let mist = Color(hex: 0xD6D6D6)       // quiet blocks (darker neutral grey)
    static let photo = Color(hex: 0x2B2D2F)      // video placeholder
    static let danger = Color(hex: 0xD24A3E)     // recording dot, wipe

    static func display(_ size: CGFloat) -> Font { .system(size: size, weight: .black) }
    static func title(_ size: CGFloat) -> Font { .system(size: size, weight: .heavy) }
    static func body(_ size: CGFloat = 17) -> Font { .system(size: size) }
    /// Mono is only for "evidence": timestamps, receipts, badges, stats.
    static func mono(_ size: CGFloat = 13) -> Font { .system(size: size, weight: .medium, design: .monospaced) }
}

enum Springs {
    static let press = Animation.spring(response: 0.22, dampingFraction: 0.9)
    static let snappy = Animation.spring(response: 0.35, dampingFraction: 0.72)
    static let pop = Animation.spring(response: 0.45, dampingFraction: 0.55)
    static let drift = Animation.spring(response: 0.5, dampingFraction: 1.0)
    static let jelly = Animation.spring(response: 0.6, dampingFraction: 0.38)
}
