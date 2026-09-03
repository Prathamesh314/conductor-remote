import SwiftUI

/// Shared navigation state for the slide-out sidebar: which section is showing
/// and whether the drawer is open.
@MainActor
final class NavState: ObservableObject {
    enum Section: Int, CaseIterable, Identifiable {
        case chats, shell, settings
        var id: Int { rawValue }
        var icon: String {
            switch self {
            case .chats: return "bubble.left.and.bubble.right.fill"
            case .shell: return "terminal.fill"
            case .settings: return "slider.horizontal.3"
            }
        }
        var label: String {
            switch self {
            case .chats: return "Chats"
            case .shell: return "Shell"
            case .settings: return "Settings"
            }
        }
    }

    @Published var section: Section = .chats
    @Published var isOpen = false

    func select(_ s: Section) {
        section = s
        isOpen = false
    }
}

/// Authenticated shell — destinations live in a slide-out sidebar toggled by the
/// hamburger button in each screen's top-left.
struct MainTabView: View {
    @EnvironmentObject var model: AppModel
    @StateObject private var nav = NavState()

    private let sidebarWidth: CGFloat = 286

    var body: some View {
        ZStack(alignment: .leading) {
            content
                .environmentObject(nav)

            if nav.isOpen {
                Color.black.opacity(0.45)
                    .ignoresSafeArea()
                    .transition(.opacity)
                    .onTapGesture { close() }
            }

            SidebarView()
                .environmentObject(nav)
                .frame(width: sidebarWidth)
                .offset(x: nav.isOpen ? 0 : -(sidebarWidth + 48))
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.86), value: nav.isOpen)
    }

    @ViewBuilder private var content: some View {
        switch nav.section {
        case .chats:    ChatsView()
        case .shell:    ShellView()
        case .settings: SettingsView()
        }
    }

    private func close() {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.86)) { nav.isOpen = false }
    }
}

/// Hamburger button that opens the sidebar. Drop into any screen's top-left
/// toolbar slot.
struct MenuButton: View {
    @EnvironmentObject var nav: NavState

    var body: some View {
        Button {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.86)) { nav.isOpen = true }
        } label: {
            Image(systemName: "line.3.horizontal")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Theme.text)
        }
    }
}

/// The drawer contents: app header + one row per destination.
private struct SidebarView: View {
    @EnvironmentObject var nav: NavState

    var body: some View {
        ZStack(alignment: .topLeading) {
            Theme.bgRaised.ignoresSafeArea()

            VStack(alignment: .leading, spacing: 6) {
                header
                    .padding(.bottom, 10)
                ForEach(NavState.Section.allCases) { section in
                    row(section)
                }
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
        .overlay(alignment: .trailing) {
            Rectangle().fill(Theme.hairline).frame(width: 1).ignoresSafeArea()
        }
        .shadow(color: .black.opacity(0.5), radius: 24, x: 10)
    }

    private var header: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Theme.glowGradient)
                .frame(width: 42, height: 42)
                .overlay(
                    Image(systemName: "macbook.and.iphone")
                        .font(.system(size: 18, weight: .medium))
                        .foregroundStyle(.white))
            VStack(alignment: .leading, spacing: 1) {
                Text("Mac Remote")
                    .font(.system(size: 17, weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.text)
                Text("Menu")
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.textFaint)
            }
            Spacer()
        }
        .padding(.top, 56)   // clear the status bar (drawer ignores safe area)
    }

    private func row(_ section: NavState.Section) -> some View {
        let selected = nav.section == section
        return Button {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.86)) { nav.select(section) }
        } label: {
            HStack(spacing: 14) {
                Image(systemName: section.icon)
                    .font(.system(size: 17, weight: .semibold))
                    .frame(width: 26)
                Text(section.label)
                    .font(.system(size: 16, weight: .semibold))
                Spacer()
            }
            .foregroundStyle(selected ? Theme.text : Theme.textDim)
            .padding(.vertical, 12)
            .padding(.horizontal, 12)
            .background {
                if selected {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(Theme.accent.opacity(0.18))
                        .overlay(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .strokeBorder(Theme.accent.opacity(0.35), lineWidth: 1))
                }
            }
        }
        .buttonStyle(PressStyle())
    }
}
