import SwiftUI

/// Renders an agent message written in Markdown into styled SwiftUI views.
///
/// Block-level structure (headings, fenced code, lists, quotes, rules) is parsed
/// here; inline formatting (**bold**, *italic*, `code`, links) is handled by
/// `AttributedString`'s inline Markdown parser. This mirrors the web UI's
/// `renderMarkdown`.
struct MarkdownMessage: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(MarkdownParser.parse(text)) { block in
                view(for: block)
            }
        }
        .tint(Theme.cyan)   // link color
    }

    @ViewBuilder
    private func view(for block: MDBlock) -> some View {
        switch block {
        case .heading(let level, let text):
            inlineText(text)
                .font(.system(size: headingSize(level), weight: .bold))
                .foregroundStyle(Theme.text)
                .padding(.top, 2)

        case .paragraph(let text):
            inlineText(text)
                .font(.system(size: 15))
                .foregroundStyle(Theme.text)
                .fixedSize(horizontal: false, vertical: true)

        case .bullet(let items):
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .top, spacing: 8) {
                        Text("•").foregroundStyle(Theme.cyan)
                        inlineText(item).foregroundStyle(Theme.text)
                    }
                    .font(.system(size: 15))
                }
            }

        case .numbered(let items):
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(items.enumerated()), id: \.offset) { i, item in
                    HStack(alignment: .top, spacing: 8) {
                        Text("\(i + 1).").foregroundStyle(Theme.cyan).monospacedDigit()
                        inlineText(item).foregroundStyle(Theme.text)
                    }
                    .font(.system(size: 15))
                }
            }

        case .quote(let text):
            HStack(spacing: 10) {
                RoundedRectangle(cornerRadius: 2).fill(Theme.accent.opacity(0.6)).frame(width: 3)
                inlineText(text)
                    .font(.system(size: 15))
                    .foregroundStyle(Theme.textDim)
            }
            .fixedSize(horizontal: false, vertical: true)

        case .code(let code):
            ScrollView(.horizontal, showsIndicators: false) {
                Text(code)
                    .font(.system(size: 13, design: .monospaced))
                    .foregroundStyle(Theme.text)
                    .textSelection(.enabled)
                    .padding(12)
            }
            .background(Theme.bg.opacity(0.6), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(Theme.hairline, lineWidth: 1))

        case .rule:
            Rectangle().fill(Theme.hairline).frame(height: 1).padding(.vertical, 2)
        }
    }

    private func inlineText(_ s: String) -> Text {
        Text(MarkdownParser.inline(s))
    }

    private func headingSize(_ level: Int) -> CGFloat {
        switch level {
        case 1: return 20
        case 2: return 17
        default: return 15
        }
    }
}

// MARK: - Model

enum MDBlock: Identifiable {
    case heading(level: Int, text: String)
    case paragraph(String)
    case bullet([String])
    case numbered([String])
    case quote(String)
    case code(String)
    case rule

    var id: String {
        switch self {
        case .heading(let l, let t): return "h\(l):\(t)"
        case .paragraph(let t):      return "p:\(t)"
        case .bullet(let i):         return "ul:\(i.joined(separator: "|"))"
        case .numbered(let i):       return "ol:\(i.joined(separator: "|"))"
        case .quote(let t):          return "q:\(t)"
        case .code(let c):           return "code:\(c)"
        case .rule:                  return "hr"
        }
    }
}

// MARK: - Parser

enum MarkdownParser {
    static func inline(_ s: String) -> AttributedString {
        let opts = AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace)
        if let a = try? AttributedString(markdown: s, options: opts) { return a }
        return AttributedString(s)
    }

    static func parse(_ src: String) -> [MDBlock] {
        var blocks: [MDBlock] = []
        var para: [String] = []
        var listItems: [String] = []
        var listOrdered = false
        var inList = false
        var quoteLines: [String] = []

        func flushPara() {
            if !para.isEmpty {
                blocks.append(.paragraph(para.joined(separator: "\n")))
                para.removeAll()
            }
        }
        func flushList() {
            if inList {
                blocks.append(listOrdered ? .numbered(listItems) : .bullet(listItems))
                listItems.removeAll()
                inList = false
            }
        }
        func flushQuote() {
            if !quoteLines.isEmpty {
                blocks.append(.quote(quoteLines.joined(separator: "\n")))
                quoteLines.removeAll()
            }
        }
        func flushAll() { flushPara(); flushList(); flushQuote() }

        let lines = src.components(separatedBy: "\n")
        var i = 0
        while i < lines.count {
            let line = lines[i]
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            // Fenced code block: collect verbatim until the closing fence.
            if trimmed.hasPrefix("```") {
                flushAll()
                var code: [String] = []
                i += 1
                while i < lines.count,
                      !lines[i].trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                    code.append(lines[i])
                    i += 1
                }
                i += 1   // skip closing fence
                blocks.append(.code(code.joined(separator: "\n")))
                continue
            }

            if trimmed.isEmpty {
                flushAll()
            } else if let h = heading(trimmed) {
                flushAll(); blocks.append(.heading(level: h.0, text: h.1))
            } else if isRule(trimmed) {
                flushAll(); blocks.append(.rule)
            } else if let item = bulletItem(line) {
                flushPara(); flushQuote()
                if inList && listOrdered { flushList() }
                inList = true; listOrdered = false
                listItems.append(item)
            } else if let item = numberedItem(line) {
                flushPara(); flushQuote()
                if inList && !listOrdered { flushList() }
                inList = true; listOrdered = true
                listItems.append(item)
            } else if let q = quoteLine(trimmed) {
                flushPara(); flushList()
                quoteLines.append(q)
            } else {
                flushList(); flushQuote()
                para.append(trimmed)
            }
            i += 1
        }
        flushAll()
        return blocks
    }

    // MARK: line matchers

    private static func heading(_ s: String) -> (Int, String)? {
        var level = 0
        var idx = s.startIndex
        while idx < s.endIndex, s[idx] == "#", level < 6 {
            level += 1; idx = s.index(after: idx)
        }
        guard level >= 1, idx < s.endIndex, s[idx] == " " else { return nil }
        let clamped = min(level, 3)
        let text = String(s[s.index(after: idx)...]).trimmingCharacters(in: .whitespaces)
        return (clamped, text)
    }

    private static func isRule(_ s: String) -> Bool {
        guard let first = s.first, "-*_".contains(first) else { return false }
        return s.count >= 3 && s.allSatisfy { $0 == first }
    }

    private static func bulletItem(_ line: String) -> String? {
        let t = line.drop { $0 == " " }
        guard let first = t.first, "-*+".contains(first) else { return nil }
        let rest = t.dropFirst()
        guard let sp = rest.first, sp == " " else { return nil }
        return String(rest.dropFirst()).trimmingCharacters(in: .whitespaces)
    }

    private static func numberedItem(_ line: String) -> String? {
        let t = line.drop { $0 == " " }
        var digits = ""
        var idx = t.startIndex
        while idx < t.endIndex, t[idx].isNumber {
            digits.append(t[idx]); idx = t.index(after: idx)
        }
        guard !digits.isEmpty, idx < t.endIndex, t[idx] == "." || t[idx] == ")" else { return nil }
        let after = t.index(after: idx)
        guard after < t.endIndex, t[after] == " " else { return nil }
        return String(t[t.index(after: after)...]).trimmingCharacters(in: .whitespaces)
    }

    private static func quoteLine(_ s: String) -> String? {
        guard s.hasPrefix(">") else { return nil }
        return String(s.dropFirst()).trimmingCharacters(in: .whitespaces)
    }
}
