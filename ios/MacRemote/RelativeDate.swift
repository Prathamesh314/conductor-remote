import Foundation

/// Turns the server's timestamps (SQLite "yyyy-MM-dd HH:mm:ss" in UTC, or ISO
/// 8601) into short relative labels like "3m", "2h", "Mon".
enum RelativeDate {
    private static let sqlite: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        f.timeZone = TimeZone(identifier: "UTC")
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    private static let iso = ISO8601DateFormatter()

    private static func parse(_ raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        if let d = sqlite.date(from: String(raw.prefix(19))) { return d }
        return iso.date(from: raw)
    }

    /// Parsed `Date` for sorting/comparison (nil when unparseable).
    static func date(_ raw: String?) -> Date? { parse(raw) }

    static func string(_ raw: String?) -> String {
        guard let date = parse(raw) else { return "" }
        let secs = Date().timeIntervalSince(date)
        if secs < 60 { return "now" }
        if secs < 3600 { return "\(Int(secs / 60))m" }
        if secs < 86_400 { return "\(Int(secs / 3600))h" }
        if secs < 604_800 {
            let f = DateFormatter(); f.dateFormat = "EEE"
            return f.string(from: date)
        }
        let f = DateFormatter(); f.dateFormat = "MMM d"
        return f.string(from: date)
    }
}
